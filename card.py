import asyncio
import copy
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from supabase import AsyncClient

# db.py の get_supabase をインポート
from db import get_supabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CardEngine")

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

async def get_user_from_token_async(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        supabase = await get_supabase()
        user_res = await supabase.auth.get_user(token)
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークンです")

# マスターデータ
CARD_DATABASE = {
    "u_01": {"id": "u_01", "name": "先鋒兵", "type": "unit", "cost": 1, "atk": 2, "hp": 1, "haste": True, "desc": "速攻"},
    "u_02": {"id": "u_02", "name": "重装兵", "type": "unit", "cost": 3, "atk": 2, "hp": 5, "taunt": True, "desc": "挑発"},
    "u_03": {"id": "u_03", "name": "魔導士", "type": "unit", "cost": 2, "atk": 3, "hp": 2, "desc": "標準アタッカー"},
    "u_04": {"id": "u_04", "name": "巨兵", "type": "unit", "cost": 6, "atk": 7, "hp": 6, "desc": "大型ユニット"},
    "u_05": {"id": "u_05", "name": "吸血鬼", "type": "unit", "cost": 4, "atk": 3, "hp": 4, "lifesteal": True, "desc": "吸血"},
    "s_01": {"id": "s_01", "name": "雷撃", "type": "spell", "cost": 2, "effect": "damage", "val": 3, "need_target": True, "desc": "単体3点"},
    "s_02": {"id": "s_02", "name": "嵐", "type": "spell", "cost": 4, "effect": "aoe_damage", "val": 2, "need_target": False, "desc": "全体2点"},
    "s_03": {"id": "s_03", "name": "治癒", "type": "spell", "cost": 2, "effect": "heal", "val": 5, "need_target": False, "desc": "自分回復5点"},
    "s_04": {"id": "s_04", "name": "補充", "type": "spell", "cost": 3, "effect": "draw", "val": 2, "need_target": False, "desc": "2枚引く"},
}

class CreateRoomRequest(BaseModel):
    wallet_id: str
    amount: int = Field(..., gt=0)

class CardGameSession:
    def __init__(self, room_id: str, host_id: str, host_name: str, host_wallet_id: str, bet_amount: int):
        self.room_id = room_id
        self.host_id = host_id
        self.host_name = host_name
        self.host_wallet_id = host_wallet_id
        self.guest_id: Optional[str] = None
        self.guest_name: Optional[str] = None
        self.guest_wallet_id: Optional[str] = None
        self.bet_amount = bet_amount
        
        self.status = "WAITING"
        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None
        self.time_limit = 60
        
        self.turn_user_id: Optional[str] = None
        self.draft_pool: List[str] = []
        self.draft_options: Dict[str, List[str]] = {}
        self.decks: Dict[str, List[dict]] = {}
        self.hands: Dict[str, List[dict]] = {}
        self.boards: Dict[str, List[dict]] = {}
        self.hp: Dict[str, int] = {}
        self.mp: Dict[str, int] = {}
        self.max_mp: Dict[str, int] = {}
        self.winner_id: Optional[str] = None
        self.message: str = "待機中..."

CARD_SESSIONS: Dict[str, CardGameSession] = {}
CLIENT_CONNECTIONS: Dict[str, Dict[str, WebSocket]] = {}

@router.get("/card", response_class=HTMLResponse)
async def get_card(request: Request):
    return templates.TemplateResponse(request=request, name="card.html")

@router.get("/api/card/rooms")
async def get_rooms():
    return {"rooms": [{"room_id": s.room_id, "host_name": s.host_name, "bet_amount": s.bet_amount} 
                      for s in CARD_SESSIONS.values() if s.status == "WAITING"]}

@router.post("/api/card/create")
async def create_room(data: CreateRoomRequest, authorization: str = Header(None)):
    user = await get_user_from_token_async(authorization)
    supabase = await get_supabase()

    if supabase:
        w_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data or w_res.data[0]["balance"] < data.amount:
            raise HTTPException(status_code=400, detail="残高が不足しています")
        
        # 部屋作成時にホストの賭け金を即時引き落とし
        new_bal = w_res.data[0]["balance"] - data.amount
        await supabase.table("wallets").update({"balance": new_bal}).eq("wallet_id", data.wallet_id).execute()

        p_res = await supabase.table("profiles").select("nickname").eq("id", user.id).execute()
        name = p_res.data[0]["nickname"] if p_res and p_res.data and "nickname" in p_res.data[0] else f"Player-{str(user.id)[:4]}"
    else:
        name = f"Player-{str(user.id)[:4]}"

    room_id = str(uuid.uuid4())[:8]
    session = CardGameSession(room_id, str(user.id), name, data.wallet_id, data.amount)
    CARD_SESSIONS[room_id] = session
    
    set_timer(session, seconds=60)
    return {"room_id": room_id}

@router.websocket("/ws/card/{room_id}")
async def card_websocket(websocket: WebSocket, room_id: str, token: str):
    await websocket.accept()
    try:
        user = await get_user_from_token_async(f"Bearer {token}")
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = str(user.id)
    session = CARD_SESSIONS.get(room_id)
    if not session:
        await websocket.send_json({"type": "ERROR", "message": "部屋が存在しません"})
        await websocket.close()
        return

    CLIENT_CONNECTIONS.setdefault(room_id, {})[user_id] = websocket

    async with session.lock:
        if session.status == "WAITING" and session.host_id != user_id:
            supabase = await get_supabase()
            if supabase:
                w_res = await supabase.table("wallets").select("*").eq("user_id", user.id).gte("balance", session.bet_amount).execute()
                if not w_res or not w_res.data:
                    await websocket.send_json({"type": "ERROR", "message": "参加資金が不足しています"})
                    await websocket.close()
                    return
                
                guest_w = w_res.data[0]
                # ゲストの賭け金を即時引き落とし
                await supabase.table("wallets").update({"balance": guest_w["balance"] - session.bet_amount}).eq("wallet_id", guest_w["wallet_id"]).execute()

                p_res = await supabase.table("profiles").select("nickname").eq("id", user.id).execute()
                session.guest_name = p_res.data[0]["nickname"] if p_res and p_res.data and "nickname" in p_res.data[0] else f"Player-{user_id[:4]}"
                session.guest_wallet_id = guest_w["wallet_id"]
            else:
                session.guest_name = f"Player-{user_id[:4]}"
                session.guest_wallet_id = f"w_{user_id[:4]}"

            session.guest_id = user_id
            start_draft_phase(session)

    await broadcast_state(room_id)

    try:
        while True:
            payload = await websocket.receive_json()
            async with session.lock:
                await process_action(session, user_id, payload)
            await broadcast_state(room_id)
    except WebSocketDisconnect:
        await handle_disconnect(room_id, user_id)

async def handle_disconnect(room_id: str, user_id: str):
    if room_id in CLIENT_CONNECTIONS and user_id in CLIENT_CONNECTIONS[room_id]:
        del CLIENT_CONNECTIONS[room_id][user_id]

    session = CARD_SESSIONS.get(room_id)
    if not session: return

    async with session.lock:
        if session.status == "WAITING":
            if user_id == session.host_id:
                session.status = "ENDED"
                session.message = "ホストが退室しました。返金して終了します。"
                await refund_wallet(session.host_wallet_id, session.bet_amount)
                await cleanup_room(room_id)
        elif session.status in ["DRAFT", "BATTLE"]:
            session.status = "ENDED"
            winner = session.guest_id if user_id == session.host_id else session.host_id
            session.winner_id = winner
            session.message = "相手が通信を切断しました。不戦勝です！"
            await settle_payout(session, winner)
            if session.timer_task: session.timer_task.cancel()
    
    await broadcast_state(room_id)
    if session and session.status == "ENDED":
        await cleanup_room(room_id)

async def refund_wallet(wallet_id: str, amount: int):
    supabase = await get_supabase()
    if not supabase or not wallet_id: return
    w_res = await supabase.table("wallets").select("balance").eq("wallet_id", wallet_id).execute()
    if w_res and w_res.data:
        await supabase.table("wallets").update({"balance": w_res.data[0]["balance"] + amount}).eq("wallet_id", wallet_id).execute()

async def cleanup_room(room_id: str):
    if room_id in CARD_SESSIONS: del CARD_SESSIONS[room_id]
    if room_id in CLIENT_CONNECTIONS:
        for ws in CLIENT_CONNECTIONS[room_id].values():
            try: await ws.close()
            except: pass
        del CLIENT_CONNECTIONS[room_id]

# --- タイマー管理系 ---
def set_timer(session: CardGameSession, seconds: int = 30):
    if session.timer_task and not session.timer_task.done():
        session.timer_task.cancel()
    session.time_limit = seconds
    session.timer_task = asyncio.create_task(run_timer(session.room_id))

async def run_timer(room_id: str):
    try:
        while True:
            await asyncio.sleep(1)
            session = CARD_SESSIONS.get(room_id)
            if not session: break
            
            async with session.lock:
                if session.status == "ENDED": break
                session.time_limit -= 1
                
                if session.time_limit <= 0:
                    if session.status == "WAITING":
                        session.status = "ENDED"
                        session.message = "対戦相手が見つかりませんでした。"
                        await refund_wallet(session.host_wallet_id, session.bet_amount)
                        await broadcast_state(room_id)
                        await cleanup_room(room_id)
                        break
                    elif session.status == "DRAFT":
                        auto_draft(session)
                    elif session.status == "BATTLE":
                        switch_turn(session)

            if session.time_limit % 5 == 0 or session.time_limit <= 5:
                await broadcast_state(room_id)
    except asyncio.CancelledError:
        pass

def start_draft_phase(session: CardGameSession):
    session.status = "DRAFT"
    session.message = "ドラフトフェーズ：カードを選択してください"
    pool = list(CARD_DATABASE.keys()) * 6
    random.shuffle(pool)
    session.draft_pool = pool
    session.decks = {session.host_id: [], session.guest_id: []}
    session.turn_user_id = session.host_id
    generate_draft_candidates(session)
    set_timer(session, 15)

def generate_draft_candidates(session: CardGameSession):
    if len(session.draft_pool) >= 3:
        session.draft_options[session.turn_user_id] = [session.draft_pool.pop() for _ in range(3)]

def auto_draft(session: CardGameSession):
    uid = session.turn_user_id
    opts = session.draft_options.get(uid, [])
    if opts:
        session.decks[uid].append(copy.deepcopy(CARD_DATABASE[opts[0]]))
    advance_draft(session)

def advance_draft(session: CardGameSession):
    h, g = session.host_id, session.guest_id
    if len(session.decks[h]) == 6 and len(session.decks[g]) == 6:
        start_battle_phase(session)
    else:
        session.turn_user_id = g if session.turn_user_id == h else h
        generate_draft_candidates(session)
        set_timer(session, 15)

def start_battle_phase(session: CardGameSession):
    session.status = "BATTLE"
    session.message = "バトル開始！"
    h, g = session.host_id, session.guest_id
    random.shuffle(session.decks[h])
    random.shuffle(session.decks[g])

    session.hp = {h: 20, g: 20}
    session.max_mp = {h: 1, g: 1}
    session.mp = {h: 1, g: 1}
    session.boards = {h: [], g: []}
    session.hands = {h: [], g: []}
    
    for uid in [h, g]:
        for _ in range(min(3, len(session.decks[uid]))):
            c = session.decks[uid].pop()
            c["instance_id"] = str(uuid.uuid4())[:8]
            session.hands[uid].append(c)

    session.turn_user_id = h
    set_timer(session, 45)

async def process_action(session: CardGameSession, user_id: str, action: dict):
    if session.status == "ENDED" or session.turn_user_id != user_id: return
    act = action.get("action")

    if session.status == "DRAFT" and act == "PICK_CARD":
        cid = action.get("card_id")
        opts = session.draft_options.get(user_id, [])
        if cid in opts:
            session.decks[user_id].append(copy.deepcopy(CARD_DATABASE[cid]))
            advance_draft(session)

    elif session.status == "BATTLE":
        if act == "PLAY_HAND":
            instance_id = action.get("card_instance_id")
            target = action.get("target")

            hand = session.hands[user_id]
            idx = next((i for i, c in enumerate(hand) if c.get("instance_id") == instance_id), None)
            if idx is None: return

            card = hand[idx]
            if session.mp[user_id] < card["cost"]: return

            session.mp[user_id] -= card["cost"]
            played = hand.pop(idx)
            session.message = f"{session.host_name if user_id == session.host_id else session.guest_name} が {played['name']} を使用！"

            if played["type"] == "unit":
                session.boards[user_id].append({
                    "instance_id": str(uuid.uuid4())[:8],
                    "card_id": played["id"],
                    "name": played["name"],
                    "atk": played["atk"],
                    "max_hp": played["hp"],
                    "curr_hp": played["hp"],
                    "can_attack": played.get("haste", False),
                    "taunt": played.get("taunt", False),
                    "lifesteal": played.get("lifesteal", False)
                })
            elif played["type"] == "spell":
                resolve_spell(session, user_id, played, target)

            await check_battle_state(session)

        elif act == "DECLARE_ATTACK":
            atk_id = action.get("attacker_id")
            target = action.get("target")

            opp_id = session.guest_id if user_id == session.host_id else session.host_id
            attacker = next((u for u in session.boards[user_id] if u["instance_id"] == atk_id), None)
            if not attacker or not attacker["can_attack"] or not target: return

            taunts = [u for u in session.boards[opp_id] if u["taunt"]]
            if taunts:
                if target.get("type") != "unit" or target.get("id") not in [u["instance_id"] for u in taunts]:
                    return # 挑発を無視している

            session.message = f"{attacker['name']} の攻撃！"
            if target.get("type") == "hero":
                session.hp[opp_id] -= attacker["atk"]
                if attacker["lifesteal"]: session.hp[user_id] = min(20, session.hp[user_id] + attacker["atk"])
                attacker["can_attack"] = False
            elif target.get("type") == "unit":
                defender = next((u for u in session.boards[opp_id] if u["instance_id"] == target.get("id")), None)
                if defender:
                    defender["curr_hp"] -= attacker["atk"]
                    attacker["curr_hp"] -= defender["atk"]
                    if attacker["lifesteal"]: session.hp[user_id] = min(20, session.hp[user_id] + attacker["atk"])
                    attacker["can_attack"] = False

            await check_battle_state(session)

        elif act == "END_TURN":
            switch_turn(session)

def resolve_spell(session: CardGameSession, user_id: str, card: dict, target: Optional[dict]):
    opp_id = session.guest_id if user_id == session.host_id else session.host_id
    eff, val = card.get("effect"), card.get("val", 0)

    if eff == "damage" and target:
        if target.get("type") == "hero" and target.get("id") == opp_id:
            session.hp[opp_id] -= val
        elif target.get("type") == "unit":
            unit = next((u for u in session.boards[opp_id] if u["instance_id"] == target.get("id")), None)
            if unit: unit["curr_hp"] -= val
    elif eff == "aoe_damage":
        for u in session.boards[opp_id]: u["curr_hp"] -= val
    elif eff == "heal":
        session.hp[user_id] = min(20, session.hp[user_id] + val)
    elif eff == "draw":
        for _ in range(val):
            if session.decks[user_id] and len(session.hands[user_id]) < 7:
                c = session.decks[user_id].pop()
                c["instance_id"] = str(uuid.uuid4())[:8]
                session.hands[user_id].append(c)

def switch_turn(session: CardGameSession):
    nxt = session.guest_id if session.turn_user_id == session.host_id else session.host_id
    session.turn_user_id = nxt
    session.message = f"{session.host_name if nxt == session.host_id else session.guest_name} のターン"
    
    session.max_mp[nxt] = min(10, session.max_mp[nxt] + 1)
    session.mp[nxt] = session.max_mp[nxt]
    for u in session.boards[nxt]: u["can_attack"] = True

    # 1. デッキがあれば通常通り1枚引く
    if session.decks[nxt] and len(session.hands[nxt]) < 7:
        c = session.decks[nxt].pop()
        c["instance_id"] = str(uuid.uuid4())[:8]
        session.hands[nxt].append(c)

    # 2. デッキが尽きて手札が0枚ならランダムに1枚生成して追加
    if len(session.hands[nxt]) == 0:
        rand_id = random.choice(list(CARD_DATABASE.keys()))
        c = copy.deepcopy(CARD_DATABASE[rand_id])
        c["instance_id"] = str(uuid.uuid4())[:8]
        session.hands[nxt].append(c)
        session.message = f"【奇跡のドロー】{session.host_name if nxt == session.host_id else session.guest_name} は手札がないためランダムなカードを生成した！"

    set_timer(session, 45)

async def check_battle_state(session: CardGameSession):
    for uid in [session.host_id, session.guest_id]:
        session.boards[uid] = [u for u in session.boards[uid] if u["curr_hp"] > 0]

    h, g = session.host_id, session.guest_id
    winner = None

    if session.hp[g] <= 0 and session.hp[h] <= 0:
        session.status = "ENDED"
        session.message = "引き分け！両者に資金を返却します。"
        await settle_payout(session, winner=None)
        return
    elif session.hp[g] <= 0: winner = h
    elif session.hp[h] <= 0: winner = g

    if winner:
        session.status = "ENDED"
        session.winner_id = winner
        win_name = session.host_name if winner == session.host_id else session.guest_name
        session.message = f"{win_name} の勝利！"
        if session.timer_task: session.timer_task.cancel()
        await settle_payout(session, winner=winner)

async def settle_payout(session: CardGameSession, winner: Optional[str]):
    supabase = await get_supabase()
    if not supabase: return
    if winner is None:
        await refund_wallet(session.host_wallet_id, session.bet_amount)
        await refund_wallet(session.guest_wallet_id, session.bet_amount)
    else:
        win_wid = session.host_wallet_id if winner == session.host_id else session.guest_wallet_id
        w_res = await supabase.table("wallets").select("balance").eq("wallet_id", win_wid).execute()
        if w_res and w_res.data:
            await supabase.table("wallets").update({"balance": w_res.data[0]["balance"] + (session.bet_amount * 2)}).eq("wallet_id", win_wid).execute()

async def broadcast_state(room_id: str):
    session = CARD_SESSIONS.get(room_id)
    if not session or room_id not in CLIENT_CONNECTIONS: return

    for uid, ws in list(CLIENT_CONNECTIONS[room_id].items()):
        try:
            state = mask_session_for_client(session, uid)
            await ws.send_json({"type": "SYNC_STATE", "payload": state})
        except Exception:
            pass

def mask_session_for_client(session: CardGameSession, target_uid: str) -> dict:
    opp_id = session.guest_id if target_uid == session.host_id else session.host_id

    masked_hands = {
        target_uid: session.hands.get(target_uid, [])
    }
    if opp_id:
        masked_hands[opp_id] = [{"instance_id": f"masked_{i}"} for i in range(len(session.hands.get(opp_id, [])))]

    return {
        "room_id": session.room_id,
        "status": session.status,
        "message": session.message,
        "time_limit": session.time_limit,
        "turn_user_id": session.turn_user_id,
        "host": {"id": session.host_id, "name": session.host_name},
        "guest": {"id": session.guest_id, "name": session.guest_name} if session.guest_id else None,
        "bet_amount": session.bet_amount,
        "draft_options": [CARD_DATABASE[cid] for cid in session.draft_options.get(target_uid, [])] if session.status == "DRAFT" else [],
        "hands": masked_hands,
        "deck_counts": {uid: len(deck) for uid, deck in session.decks.items()},
        "my_deck": session.decks.get(target_uid, []),  # ドラフト履歴表示用データ
        "boards": session.boards,
        "hp": session.hp,
        "mp": session.mp,
        "max_mp": session.max_mp,
        "winner_id": session.winner_id,
        "your_user_id": target_uid
    }
