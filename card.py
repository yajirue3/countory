import asyncio
import uuid
import random
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Header, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from supabase import create_client, Client
import os

router = APIRouter()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

CARD_SESSIONS: Dict[str, "CardSession"] = {}
CLIENT_CONNECTIONS: Dict[str, Dict[str, WebSocket]] = {}

class CreateRoomRequest(BaseModel):
    wallet_id: str
    bet_amount: int

class Card:
    def __init__(self, card_type: str, atk: int):
        self.type = card_type  # "FIRE", "WATER", "TREE"
        self.atk = atk

    def to_dict(self):
        return {"type": self.type, "atk": self.atk}

class CardSession:
    def __init__(self, room_id: str, host_id: str, host_name: str, host_wallet_id: str, bet_amount: int):
        self.room_id = room_id
        self.host_id = host_id
        self.host_name = host_name
        self.host_wallet_id = host_wallet_id
        self.guest_id: Optional[str] = None
        self.guest_name: Optional[str] = None
        self.guest_wallet_id: Optional[str] = None
        self.bet_amount = bet_amount
        
        self.status = "WAITING"  # WAITING, BATTLE, ENDED
        self.message = "対戦相手の参加を待っています..."
        self.host_hp = 100
        self.guest_hp = 100
        self.winner_id: Optional[str] = None
        
        # 手札・選択
        self.host_hand: List[Card] = []
        self.guest_hand: List[Card] = []
        self.host_selected: Optional[Card] = None
        self.guest_selected: Optional[Card] = None
        
        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None
        self.timer_seconds = 20

    def generate_hand(self) -> List[Card]:
        types = ["FIRE", "WATER", "TREE"]
        return [Card(random.choice(types), random.randint(15, 35)) for _ in range(3)]

async def async_supabase_exec(query):
    return await asyncio.to_thread(query.execute)

async def get_user_from_token_async(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    user_res = await asyncio.to_thread(supabase.auth.get_user, token)
    return user_res.user

@router.post("/api/card/create")
async def create_room(data: CreateRoomRequest, authorization: str = Header(None)):
    user = await get_user_from_token_async(authorization)
    if data.bet_amount <= 0:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上にしてください")

    w_res = await async_supabase_exec(
        supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id)
    )
    if not w_res.data or w_res.data[0]["balance"] < data.bet_amount:
        raise HTTPException(status_code=400, detail="残高が不足しています")

    p_res = await async_supabase_exec(supabase.table("profiles").select("nickname").eq("id", user.id))
    host_name = p_res.data[0]["nickname"] if p_res and p_res.data else f"Player-{str(user.id)[:4]}"

    room_id = str(uuid.uuid4())[:8]
    session = CardSession(room_id, str(user.id), host_name, data.wallet_id, data.bet_amount)
    CARD_SESSIONS[room_id] = session

    # 賭け金を即時引き落とし
    new_bal = w_res.data[0]["balance"] - data.bet_amount
    await async_supabase_exec(supabase.table("wallets").update({"balance": new_bal}).eq("wallet_id", data.wallet_id))

    return {"room_id": room_id}

async def process_turn_battle(session: CardSession):
    """じゃんけん属性計算 & ダメージ計算"""
    h_card, g_card = session.host_selected, session.guest_selected
    h_dmg, g_dmg = h_card.atk, g_card.atk

    # 属性相性判定 (FIRE > TREE > WATER > FIRE)
    if (h_card.type == "FIRE" and g_card.type == "TREE") or \
       (h_card.type == "TREE" and g_card.type == "WATER") or \
       (h_card.type == "WATER" and g_card.type == "FIRE"):
        h_dmg = int(h_dmg * 1.5)
        g_dmg = 0
    elif (g_card.type == "FIRE" and h_card.type == "TREE") or \
         (g_card.type == "TREE" and h_card.type == "WATER") or \
         (g_card.type == "WATER" and h_card.type == "FIRE"):
        g_dmg = int(g_dmg * 1.5)
        h_dmg = 0

    session.guest_hp = max(0, session.guest_hp - h_dmg)
    session.host_hp = max(0, session.host_hp - g_dmg)

    session.host_selected = None
    session.guest_selected = None

    if session.host_hp <= 0 or session.guest_hp <= 0:
        session.status = "ENDED"
        if session.host_hp > session.guest_hp:
            session.winner_id = session.host_id
            session.message = f"🎉 {session.host_name} の勝利！"
        else:
            session.winner_id = session.guest_id
            session.message = f"🎉 {session.guest_name} の勝利！"
        await settle_payout(session, session.winner_id)
    else:
        session.message = f"ターン終了！ Host:{h_dmg}ダメ / Guest:{g_dmg}ダメ"
        session.host_hand = session.generate_hand()
        session.guest_hand = session.generate_hand()

async def broadcast_state(room_id: str):
    session = CARD_SESSIONS.get(room_id)
    if not session or room_id not in CLIENT_CONNECTIONS:
        return

    for uid, ws in list(CLIENT_CONNECTIONS[room_id].items()):
        payload = {
            "your_user_id": uid,
            "status": session.status,
            "message": session.message,
            "host_id": session.host_id,
            "host_name": session.host_name,
            "host_hp": session.host_hp,
            "guest_id": session.guest_id,
            "guest_name": session.guest_name,
            "guest_hp": session.guest_hp,
            "timer_seconds": session.timer_seconds,
            "host_hand": [c.to_dict() for c in session.host_hand] if uid == session.host_id else [],
            "guest_hand": [c.to_dict() for c in session.guest_hand] if uid == session.guest_id else []
        }
        try:
            await ws.send_json(payload)
        except Exception:
            pass

async def settle_payout(session: CardSession, winner_id: Optional[str]):
    if not winner_id or not supabase: return
    total_pot = session.bet_amount * 2
    target_wallet = session.host_wallet_id if winner_id == session.host_id else session.guest_wallet_id
    
    w_res = await async_supabase_exec(supabase.table("wallets").select("balance").eq("wallet_id", target_wallet))
    if w_res and w_res.data:
        curr_bal = w_res.data[0]["balance"]
        await async_supabase_exec(supabase.table("wallets").update({"balance": curr_bal + total_pot}).eq("wallet_id", target_wallet))

async def refund_host(session: CardSession):
    if not supabase: return
    w_res = await async_supabase_exec(supabase.table("wallets").select("balance").eq("wallet_id", session.host_wallet_id))
    if w_res and w_res.data:
        curr_bal = w_res.data[0]["balance"]
        await async_supabase_exec(supabase.table("wallets").update({"balance": curr_bal + session.bet_amount}).eq("wallet_id", session.host_wallet_id))

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
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 排他制御による同時参加ガード
    async with session.lock:
        if user_id != session.host_id:
            if session.status != "WAITING" or session.guest_id is not None:
                await websocket.send_json({"type": "ERROR", "message": "この部屋はすでに満員です"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            w_res = await async_supabase_exec(supabase.table("wallets").select("*").eq("user_id", user.id).gte("balance", session.bet_amount))
            if not w_res or not w_res.data:
                await websocket.send_json({"type": "ERROR", "message": "参加資金が不足しています"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            guest_wallet = w_res.data[0]
            p_res = await async_supabase_exec(supabase.table("profiles").select("nickname").eq("id", user.id))
            
            session.guest_id = user_id
            session.guest_name = p_res.data[0]["nickname"] if p_res and p_res.data else f"Player-{user_id[:4]}"
            session.guest_wallet_id = guest_wallet["wallet_id"]
            session.status = "BATTLE"
            session.message = "バトル開始！カードを選択してください"
            
            session.host_hand = session.generate_hand()
            session.guest_hand = session.generate_hand()

            await async_supabase_exec(
                supabase.table("wallets").update({"balance": guest_wallet["balance"] - session.bet_amount}).eq("wallet_id", guest_wallet["wallet_id"])
            )

        CLIENT_CONNECTIONS.setdefault(room_id, {})[user_id] = websocket

    await broadcast_state(room_id)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "SUBMIT_CARD":
                async with session.lock:
                    idx = data.get("hand_index")
                    if user_id == session.host_id and session.host_hand:
                        session.host_selected = session.host_hand[idx]
                    elif user_id == session.guest_id and session.guest_hand:
                        session.guest_selected = session.guest_hand[idx]

                    if session.host_selected and session.guest_selected:
                        await process_turn_battle(session)

                await broadcast_state(room_id)

    except WebSocketDisconnect:
        if room_id in CLIENT_CONNECTIONS and user_id in CLIENT_CONNECTIONS[room_id]:
            del CLIENT_CONNECTIONS[room_id][user_id]

        async with session.lock:
            if session.status == "WAITING" and user_id == session.host_id:
                await refund_host(session)
                CARD_SESSIONS.pop(room_id, None)
            elif session.status == "BATTLE":
                session.status = "ENDED"
                winner_id = session.guest_id if user_id == session.host_id else session.host_id
                session.winner_id = winner_id
                session.message = "相手の切断により不戦勝となりました！"
                await settle_payout(session, winner_id)
                await broadcast_state(room_id)
                CARD_SESSIONS.pop(room_id, None)
