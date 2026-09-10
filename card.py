import asyncio
import copy
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Header, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DuelEngine")

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def get_authenticated_user(token: str) -> Any:
    if not supabase:
        return type("User", (), {"id": f"usr_{token[:8]}"})()
    try:
        res = supabase.auth.get_user(token)
        if not res or not res.user:
            raise HTTPException(status_code=401, detail="認証トークンが無効です")
        return res.user
    except Exception:
        raise HTTPException(status_code=401, detail="認証エラー")

# --- カード定義（データ構造の定数化） ---
CARD_DATABASE = {
    "u_01": {"id": "u_01", "name": "先鋒の歩兵", "type": "unit", "cost": 1, "atk": 2, "hp": 1, "haste": True, "desc": "速攻（召喚ターンに攻撃可能）"},
    "u_02": {"id": "u_02", "name": "ガーディアン", "type": "unit", "cost": 3, "atk": 2, "hp": 5, "taunt": True, "desc": "挑発（敵の攻撃を強制的に引き受ける）"},
    "u_03": {"id": "u_03", "name": "魔導の神官", "type": "unit", "cost": 2, "atk": 3, "hp": 2, "desc": "高火力な下級ユニット"},
    "u_04": {"id": "u_04", "name": "戦場の支配者", "type": "unit", "cost": 6, "atk": 7, "hp": 6, "desc": "戦局を覆す大型ユニット"},
    "u_05": {"id": "u_05", "name": "ブラッドナイト", "type": "unit", "cost": 4, "atk": 3, "hp": 4, "lifesteal": True, "desc": "吸血（与ダメージ分プレイヤーHP回復）"},
    "s_01": {"id": "s_01", "name": "ライトニングボルト", "type": "spell", "cost": 2, "effect": "damage", "val": 3, "need_target": True, "desc": "指定ターゲットに3ダメージ"},
    "s_02": {"id": "s_02", "name": "サンダーストーム", "type": "spell", "cost": 4, "effect": "aoe_damage", "val": 2, "need_target": False, "desc": "敵盤面全体に2ダメージ"},
    "s_03": {"id": "s_03", "name": "聖なる治癒", "type": "spell", "cost": 2, "effect": "heal", "val": 5, "need_target": False, "desc": "自ヒーローのHPを5回復"},
    "s_04": {"id": "s_04", "name": "戦術的補充", "type": "spell", "cost": 3, "effect": "draw", "val": 2, "need_target": False, "desc": "カードを2枚ドロー"},
}

class CreateRoomRequest(BaseModel):
    wallet_id: str
    bet_amount: int = Field(..., gt=0)

class GameSession:
    def __init__(self, room_id: str, host_id: str, host_name: str, host_wallet: str, bet_amount: int):
        self.room_id = room_id
        self.host_id = host_id
        self.host_name = host_name
        self.host_wallet = host_wallet
        self.guest_id: Optional[str] = None
        self.guest_name: Optional[str] = None
        self.guest_wallet: Optional[str] = None
        self.bet_amount = bet_amount
        
        self.status = "WAITING"  # WAITING, DRAFT, BATTLE, ENDED
        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None
        self.time_limit = 30
        
        self.turn_user_id: Optional[str] = None
        self.turn_count = 0
        self.draft_pool: List[str] = []
        self.draft_options: Dict[str, List[str]] = {}
        self.decks: Dict[str, List[dict]] = {}
        self.hands: Dict[str, List[dict]] = {}
        self.boards: Dict[str, List[dict]] = {}
        self.hp: Dict[str, int] = {}
        self.mp: Dict[str, int] = {}
        self.max_mp: Dict[str, int] = {}
        self.winner_id: Optional[str] = None

SESSIONS: Dict[str, GameSession] = {}
CLIENT_CONNECTIONS: Dict[str, Dict[str, WebSocket]] = {}

@router.get("/card", response_class=HTMLResponse)
def get_card_page(request: Request):
    return templates.TemplateResponse(request=request, name="card.html")

@router.get("/api/card/rooms")
def get_available_rooms():
    return {"rooms": [{"room_id": s.room_id, "host_name": s.host_name, "bet_amount": s.bet_amount} 
                      for s in SESSIONS.values() if s.status == "WAITING"]}

@router.post("/api/card/create")
async def create_room_api(data: CreateRoomRequest, authorization: str = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else ""
    user = get_authenticated_user(token)

    if supabase:
        res = supabase.table("wallets").select("balance").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not res.data or res.data[0]["balance"] < data.bet_amount:
            raise HTTPException(status_code=400, detail="残高が不足しています")
        prof = supabase.table("profiles").select("nickname").eq("id", user.id).execute()
        name = prof.data[0]["nickname"] if prof.data else "Player"
    else:
        name = f"User-{str(user.id)[:4]}"

    room_id = str(uuid.uuid4())[:8]
    session = GameSession(room_id, str(user.id), name, data.wallet_id, data.bet_amount)
    SESSIONS[room_id] = session
    return {"room_id": room_id}

@router.websocket("/ws/card/{room_id}")
async def game_websocket(websocket: WebSocket, room_id: str, token: str):
    await websocket.accept()
    try:
        user = get_authenticated_user(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = str(user.id)
    session = SESSIONS.get(room_id)
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    CLIENT_CONNECTIONS.setdefault(room_id, {})[user_id] = websocket

    async with session.lock:
        if session.status == "WAITING" and session.host_id != user_id:
            # ゲスト参加と資金拘束
            if supabase:
                w_res = supabase.table("wallets").select("wallet_id, balance").eq("user_id", user.id).gte("balance", session.bet_amount).execute()
                if not w_res.data:
                    await websocket.send_json({"type": "ERROR", "message": "参加に必要な資金が不足しています"})
                    await websocket.close()
                    return
                p_res = supabase.table("profiles").select("nickname").eq("id", user.id).execute()
                session.guest_name = p_res.data[0]["nickname"] if p_res.data else "Guest"
                session.guest_wallet = w_res.data[0]["wallet_id"]
            else:
                session.guest_name = f"User-{user_id[:4]}"
                session.guest_wallet = f"w_{user_id[:4]}"

            session.guest_id = user_id
            process_escrow_deduction(session)
            start_draft_phase(session)

    await broadcast_session_state(room_id)

    try:
        while True:
            payload = await websocket.receive_json()
            async with session.lock:
                await handle_client_action(session, user_id, payload)
    except WebSocketDisconnect:
        if room_id in CLIENT_CONNECTIONS and user_id in CLIENT_CONNECTIONS[room_id]:
            del CLIENT_CONNECTIONS[room_id][user_id]

def process_escrow_deduction(session: GameSession):
    if not supabase: return
    for wid in [session.host_wallet, session.guest_wallet]:
        curr = supabase.table("wallets").select("balance").eq("wallet_id", wid).execute().data[0]["balance"]
        supabase.table("wallets").update({"balance": curr - session.bet_amount}).eq("wallet_id", wid).execute()

def start_draft_phase(session: GameSession):
    session.status = "DRAFT"
    pool = list(CARD_DATABASE.keys()) * 6
    random.shuffle(pool)
    session.draft_pool = pool
    session.decks = {session.host_id: [], session.guest_id: []}
    session.turn_user_id = session.host_id
    generate_draft_candidates(session)
    arm_turn_timer(session)

def generate_draft_candidates(session: GameSession):
    if len(session.draft_pool) >= 3:
        session.draft_options[session.turn_user_id] = [session.draft_pool.pop() for _ in range(3)]

def arm_turn_timer(session: GameSession):
    if session.timer_task and not session.timer_task.done():
        session.timer_task.cancel()
    session.time_limit = 30
    session.timer_task = asyncio.create_task(run_session_timer(session.room_id))

async def run_session_timer(room_id: str):
    try:
        while True:
            await asyncio.sleep(1)
            session = SESSIONS.get(room_id)
            if not session: break
            async with session.lock:
                if session.status == "ENDED": break
                session.time_limit -= 1
                if session.time_limit <= 0:
                    if session.status == "DRAFT":
                        force_draft_selection(session)
                    elif session.status == "BATTLE":
                        switch_battle_turn(session)
                    await broadcast_session_state(room_id)
    except asyncio.CancelledError:
        pass

def force_draft_selection(session: GameSession):
    uid = session.turn_user_id
    opts = session.draft_options.get(uid, [])
    if opts:
        session.decks[uid].append(copy.deepcopy(CARD_DATABASE[opts[0]]))
    advance_draft_loop(session)

def advance_draft_loop(session: GameSession):
    h, g = session.host_id, session.guest_id
    if len(session.decks[h]) == 6 and len(session.decks[g]) == 6:
        initiate_battle_phase(session)
    else:
        session.turn_user_id = g if session.turn_user_id == h else h
        generate_draft_candidates(session)
        arm_turn_timer(session)

def initiate_battle_phase(session: GameSession):
    session.status = "BATTLE"
    h, g = session.host_id, session.guest_id
    random.shuffle(session.decks[h])
    random.shuffle(session.decks[g])

    session.hp = {h: 20, g: 20}
    session.max_mp = {h: 1, g: 1}
    session.mp = {h: 1, g: 1}
    session.boards = {h: [], g: []}
    session.hands = {
        h: [session.decks[h].pop() for _ in range(min(3, len(session.decks[h])))],
        g: [session.decks[g].pop() for _ in range(min(3, len(session.decks[g])))]
    }
    session.turn_user_id = h
    arm_turn_timer(session)

async def handle_client_action(session: GameSession, user_id: str, action: dict):
    if session.status == "ENDED" or session.turn_user_id != user_id:
        return  # ターン権限がない操作は完全無視

    act_type = action.get("action")

    if session.status == "DRAFT" and act_type == "PICK_CARD":
        cid = action.get("card_id")
        opts = session.draft_options.get(user_id, [])
        if cid in opts:
            session.decks[user_id].append(copy.deepcopy(CARD_DATABASE[cid]))
            advance_draft_loop(session)
            await broadcast_session_state(session.room_id)

    elif session.status == "BATTLE":
        if act_type == "PLAY_HAND":
            instance_id = action.get("card_instance_id")
            target = action.get("target") # {"type": "hero"/"unit", "id": str}
            
            # 手札所有権バリデーション
            hand = session.hands[user_id]
            card_idx = next((i for i, c in enumerate(hand) if c.get("instance_id") == instance_id), None)
            if card_idx is None: return

            card = hand[card_idx]
            if session.mp[user_id] < card["cost"]: return  # マナ不正利用検知

            # プレイ実行
            session.mp[user_id] -= card["cost"]
            played_card = hand.pop(card_idx)

            if played_card["type"] == "unit":
                session.boards[user_id].append({
                    "instance_id": str(uuid.uuid4())[:8],
                    "card_id": played_card["id"],
                    "name": played_card["name"],
                    "atk": played_card["atk"],
                    "max_hp": played_card["hp"],
                    "curr_hp": played_card["hp"],
                    "can_attack": played_card.get("haste", False),
                    "taunt": played_card.get("taunt", False),
                    "lifesteal": played_card.get("lifesteal", False)
                })
            elif played_card["type"] == "spell":
                execute_spell(session, user_id, played_card, target)

            evaluate_field_and_game_over(session)
            await broadcast_session_state(session.room_id)

        elif act_type == "DECLARE_ATTACK":
            atk_id = action.get("attacker_id")
            target = action.get("target")  # {"type": "hero"/"unit", "id": str}

            opp_id = session.guest_id if user_id == session.host_id else session.host_id
            attacker = next((u for u in session.boards[user_id] if u["instance_id"] == atk_id), None)
            
            if not attacker or not attacker["can_attack"]: return

            # 挑発（Taunt）バリデーション: 挑発が存在する場合は挑発対象以外への攻撃を即拒否
            taunt_units = [u for u in session.boards[opp_id] if u["taunt"]]
            if taunt_units:
                if target.get("type") != "unit" or target.get("id") not in [u["instance_id"] for u in taunt_units]:
                    return  # ガード無視の不正攻撃を排除

            if target.get("type") == "hero":
                session.hp[opp_id] -= attacker["atk"]
                if attacker["lifesteal"]: session.hp[user_id] = min(20, session.hp[user_id] + attacker["atk"])
                attacker["can_attack"] = False

            elif target.get("type") == "unit":
                defender = next((u for u in session.boards[opp_id] if u["instance_id"] == target.get("id")), None)
                if defender:
                    defender["curr_hp"] -= attacker["atk"]
                    attacker["curr_hp"] -= defender["atk"]  # 反撃処理
                    if attacker["lifesteal"]: session.hp[user_id] = min(20, session.hp[user_id] + attacker["atk"])
                    attacker["can_attack"] = False

            evaluate_field_and_game_over(session)
            await broadcast_session_state(session.room_id)

        elif act_type == "END_TURN":
            switch_battle_turn(session)
            await broadcast_session_state(session.room_id)

def execute_spell(session: GameSession, user_id: str, card: dict, target: Optional[dict]):
    opp_id = session.guest_id if user_id == session.host_id else session.host_id
    eff = card.get("effect")
    val = card.get("val", 0)

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

def switch_battle_turn(session: GameSession):
    next_user = session.guest_id if session.turn_user_id == session.host_id else session.host_id
    session.turn_user_id = next_user
    session.turn_count += 1

    session.max_mp[next_user] = min(10, session.max_mp[next_user] + 1)
    session.mp[next_user] = session.max_mp[next_user]

    for u in session.boards[next_user]: u["can_attack"] = True

    if session.decks[next_user] and len(session.hands[next_user]) < 7:
        c = session.decks[next_user].pop()
        c["instance_id"] = str(uuid.uuid4())[:8]
        session.hands[next_user].append(c)

    arm_turn_timer(session)

def evaluate_field_and_game_over(session: GameSession):
    # 死亡ユニットの除外
    for uid in [session.host_id, session.guest_id]:
        session.boards[uid] = [u for u in session.boards[uid] if u["curr_hp"] > 0]

    h, g = session.host_id, session.guest_id
    winner = None

    if session.hp[g] <= 0 and session.hp[h] <= 0:
        session.status = "ENDED"
        payout_escrow(session, winner=None)
        return
    elif session.hp[g] <= 0: winner = h
    elif session.hp[h] <= 0: winner = g

    if winner:
        session.status = "ENDED"
        session.winner_id = winner
        if session.timer_task: session.timer_task.cancel()
        payout_escrow(session, winner=winner)

def payout_escrow(session: GameSession, winner: Optional[str]):
    if not supabase: return
    if winner is None:  # 引き分け返金
        for wid in [session.host_wallet, session.guest_wallet]:
            bal = supabase.table("wallets").select("balance").eq("wallet_id", wid).execute().data[0]["balance"]
            supabase.table("wallets").update({"balance": bal + session.bet_amount}).eq("wallet_id", wid).execute()
    else:  # 勝者総取り
        win_wallet = session.host_wallet if winner == session.host_id else session.guest_wallet
        bal = supabase.table("wallets").select("balance").eq("wallet_id", win_wallet).execute().data[0]["balance"]
        supabase.table("wallets").update({"balance": bal + (session.bet_amount * 2)}).eq("wallet_id", win_wallet).execute()

async def broadcast_session_state(room_id: str):
    session = SESSIONS.get(room_id)
    if not session or room_id not in CLIENT_CONNECTIONS: return

    for uid, ws in list(CLIENT_CONNECTIONS[room_id].items()):
        try:
            state = sanitize_session_for_client(session, uid)
            await ws.send_json({"type": "SYNC_STATE", "payload": state})
        except Exception:
            pass

def sanitize_session_for_client(session: GameSession, target_user_id: str) -> dict:
    """イカサマ防止: 相手に不要な非公開情報を完全にカットした安全なJSONを構築"""
    opp_id = session.guest_id if target_user_id == session.host_id else session.host_id

    # 相手の手札は枚数だけ開示（IDや効果は遮蔽）
    sanitized_hands = {
        target_user_id: session.hands.get(target_user_id, []),
        opp_id: [{"instance_id": f"masked_{i}"} for i in range(len(session.hands.get(opp_id, [])))]
    }

    return {
        "room_id": session.room_id,
        "status": session.status,
        "time_limit": session.time_limit,
        "turn_user_id": session.turn_user_id,
        "host": {"id": session.host_id, "name": session.host_name},
        "guest": {"id": session.guest_id, "name": session.guest_name},
        "bet_amount": session.bet_amount,
        "draft_options": [CARD_DATABASE[cid] for cid in session.draft_options.get(target_user_id, [])] if session.status == "DRAFT" else [],
        "hands": sanitized_hands,
        "deck_counts": {uid: len(deck) for uid, deck in session.decks.items()},
        "boards": session.boards,
        "hp": session.hp,
        "mp": session.mp,
        "max_mp": session.max_mp,
        "winner_id": session.winner_id
    }
