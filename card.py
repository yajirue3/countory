import asyncio
import uuid
import random
import os
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Header, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client

router = APIRouter()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

CARD_SESSIONS: Dict[str, "CardSession"] = {}
CLIENT_CONNECTIONS: Dict[str, Dict[str, WebSocket]] = {}

# ==========================================
# 1. HTML ページ表示用ルート (Not Found 対策)
# ==========================================
@router.get("/card", response_class=HTMLResponse)
async def get_card_page():
    """/card にアクセスされた際に直接HTMLを返します"""
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
        <title>村岡王国 - 究極カード対戦</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Black+Ops+One&family=M+PLUS+1p:wght@900&display=swap');
            :root { --neon-pink: #ff007f; --neon-cyan: #00f3ff; --neon-yellow: #ffe600; --neon-green: #00ff66; --neon-red: #ff003c; }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'M PLUS 1p', sans-serif; background: #000; color: #fff; min-height: 100dvh; display: flex; justify-content: center; align-items: center; padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); user-select: none; overflow: hidden; }
            .container { width: 100%; max-width: 480px; height: 100dvh; max-height: 920px; display: flex; flex-direction: column; justify-content: space-between; padding: 8px; gap: 6px; }
            .card-main { background: rgba(10, 2, 18, 0.95); border: 2px solid var(--neon-pink); border-radius: 16px; padding: 10px; box-shadow: 0 0 30px rgba(255, 0, 127, 0.5); display: flex; flex-direction: column; gap: 8px; height: 100%; overflow: hidden; position: relative; }
            .header-area { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--neon-cyan); padding-bottom: 4px; }
            .header-title { font-size: clamp(1.1rem, 4vw, 1.4rem); font-weight: 900; color: var(--neon-yellow); }
            .btn-rule-open { background: rgba(0, 243, 255, 0.2); border: 1px solid var(--neon-cyan); color: var(--neon-cyan); padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; cursor: pointer; }
            .status-display { background: #000; border: 2px solid var(--neon-cyan); border-radius: 12px; padding: 8px; text-align: center; }
            .status-text { font-size: clamp(0.85rem, 3.2vw, 1.05rem); font-weight: 900; color: var(--neon-yellow); }
            .timer-display { font-size: 1.5rem; font-weight: 900; color: var(--neon-red); font-family: 'Black Ops One', monospace; }
            .field { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; flex: 1; }
            .player-box { background: rgba(20, 20, 35, 0.9); border: 1.5px solid rgba(0, 243, 255, 0.4); border-radius: 12px; padding: 8px; display: flex; flex-direction: column; align-items: center; justify-content: space-between; }
            .player-name { font-size: clamp(0.8rem, 3vw, 0.95rem); color: var(--neon-cyan); font-weight: bold; }
            .hp-bar-container { width: 100%; height: 14px; background: #222; border-radius: 7px; overflow: hidden; border: 1px solid #444; position: relative; }
            .hp-bar-fill { height: 100%; background: linear-gradient(90deg, #ff0055, #00ff66); width: 100%; transition: width 0.4s ease; }
            .hp-text { position: absolute; top: 0; left: 0; right: 0; bottom: 0; font-size: 0.65rem; text-align: center; line-height: 14px; font-weight: bold; color: #fff; }
            .card-slot { width: 100%; max-width: 110px; aspect-ratio: 2/3; border: 2px dashed rgba(255,255,255,0.3); border-radius: 10px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: rgba(0,0,0,0.6); }
            .hand-container { display: flex; gap: 6px; justify-content: center; min-height: 95px; background: rgba(0,0,0,0.4); padding: 6px; border-radius: 10px; border: 1px solid rgba(255,0,127,0.3); }
            .card-item { flex: 1; max-width: 75px; aspect-ratio: 2/3; background: linear-gradient(135deg, #1f1c2c, #3a3858); border: 2px solid var(--neon-cyan); border-radius: 8px; display: flex; flex-direction: column; align-items: center; justify-content: space-around; padding: 4px; cursor: pointer; }
            .card-item.selected { border-color: var(--neon-yellow); box-shadow: 0 0 15px var(--neon-yellow); transform: translateY(-8px); }
            .card-item.disabled { opacity: 0.3; filter: grayscale(1); cursor: not-allowed; }
            .controls { display: flex; flex-direction: column; gap: 6px; }
            .input-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
            select, input { width: 100%; padding: 8px; border-radius: 8px; border: 1.5px solid var(--neon-cyan); background: #0d0d18; color: #fff; font-size: 0.8rem; }
            button { width: 100%; padding: 10px; border: none; border-radius: 10px; font-weight: 900; cursor: pointer; }
            .btn-action { background: linear-gradient(135deg, #ff0055, #ff00a0); color: #fff; }
            .btn-submit { background: linear-gradient(135deg, #00ff66, #009933); color: #000; }
            .btn-back { background: #111; color: #aaa; border: 1px solid #333; font-size: 0.75rem; padding: 6px; }
            .rule-modal { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.95); border-radius: 16px; padding: 16px; display: none; flex-direction: column; gap: 12px; z-index: 100; }
            .rule-modal.active { display: flex; }
            .rule-modal h2 { color: var(--neon-yellow); border-bottom: 2px solid var(--neon-pink); }
            .rule-modal ul { font-size: 0.8rem; line-height: 1.6; color: #ddd; padding-left: 18px; }
        </style>
    </head>
    <body>
    <div class="container">
        <div class="card-main">
            <div class="header-area">
                <div class="header-title">⚔️ 属性カードバトル ⚔️</div>
                <button class="btn-rule-open" onclick="toggleRule(true)">📖 ルール</button>
            </div>

            <div class="status-display">
                <div id="status-text" class="status-text">部屋を作成するか接続を待ってください</div>
                <div id="timer" class="timer-display">--</div>
            </div>

            <div class="field">
                <div class="player-box">
                    <div id="host-name" class="player-name">Host: 待機中</div>
                    <div class="hp-bar-container">
                        <div id="host-hp-fill" class="hp-bar-fill"></div>
                        <div id="host-hp-text" class="hp-text">100/100</div>
                    </div>
                    <div id="host-card" class="card-slot"><div style="font-size:1.8rem;">❓</div></div>
                </div>
                <div class="player-box">
                    <div id="guest-name" class="player-name">Guest: 待機中</div>
                    <div class="hp-bar-container">
                        <div id="guest-hp-fill" class="hp-bar-fill"></div>
                        <div id="guest-hp-text" class="hp-text">100/100</div>
                    </div>
                    <div id="guest-card" class="card-slot"><div style="font-size:1.8rem;">❓</div></div>
                </div>
            </div>

            <div id="hand-area" class="hand-container"></div>

            <div class="controls">
                <div class="input-row" id="setup-inputs">
                    <select id="wallet-select"></select>
                    <input type="number" id="bet-amount" value="100" min="10" placeholder="賭け金">
                </div>
                <button id="main-btn" class="btn-action">🚀 部屋を作成して待機</button>
                <button id="submit-card-btn" class="btn-submit" style="display:none;" disabled>🔥 カードを提出する</button>
                <button class="btn-back" onclick="location.href='/casino'">◀ カジノへ戻る</button>
            </div>

            <div id="rule-modal" class="rule-modal">
                <h2>📜 バトルのルール</h2>
                <ul>
                    <li><strong>属性相性 (じゃんけん):</strong><br>🔥 炎 > 🌲 樹 > 💧 水 > 🔥 炎</li>
                    <li><strong>ダメージ計算:</strong><br>属性で勝利すると <strong>【攻撃力(ATK) × 1.5倍】</strong> のダメージを与えます。あいこは等倍ダメージです。</li>
                    <li><strong>勝利条件:</strong><br>相手のHP(100)を先に0にした方が勝ちとなり、賭け金の総額を獲得します。</li>
                </ul>
                <button class="btn-action" onclick="toggleRule(false)">閉じる</button>
            </div>
        </div>
    </div>

    <script>
        const token = localStorage.getItem("access_token");
        if (!token) window.location.href = "/";

        let ws = null, currentRoomId = null, myUserId = null, selectedHandIndex = null, currentHandData = [];

        document.addEventListener("DOMContentLoaded", () => {
            loadWallets();
            document.getElementById("main-btn").addEventListener("click", createRoom);
            document.getElementById("submit-card-btn").addEventListener("click", submitCard);
        });

        function toggleRule(show) { document.getElementById("rule-modal").classList.toggle("active", show); }

        async function loadWallets() {
            try {
                const res = await fetch("/api/wallets", { headers: { "Authorization": `Bearer ${token}` } });
                if (!res.ok) return;
                const wallets = await res.json();
                document.getElementById("wallet-select").innerHTML = wallets.map(w => `<option value="${w.wallet_id}">${w.wallet_name}: ${w.balance}G</option>`).join('');
            } catch (e) { console.error(e); }
        }

        async function createRoom() {
            const walletId = document.getElementById("wallet-select").value;
            const amount = parseInt(document.getElementById("bet-amount").value, 10);
            if (!walletId || !amount) return alert("入力内容を確認してください");

            const res = await fetch("/api/card/create", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                body: JSON.stringify({ wallet_id: walletId, bet_amount: amount })
            });
            const data = await res.json();
            if (!res.ok) return alert(data.detail);
            connectWebSocket(data.room_id);
        }

        function connectWebSocket(roomId) {
            currentRoomId = roomId;
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            ws = new WebSocket(`${protocol}//${location.host}/ws/card/${roomId}?token=${token}`);

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === "ERROR") return alert(data.message);
                renderState(data);
            };
        }

        function renderState(state) {
            myUserId = state.your_user_id;
            document.getElementById("status-text").innerText = state.message;
            document.getElementById("timer").innerText = state.timer_seconds ?? "--";
            document.getElementById("host-name").innerText = state.host_name || "Host";
            document.getElementById("guest-name").innerText = state.guest_name || "待機中...";
            document.getElementById("host-hp-fill").style.width = `${state.host_hp}%`;
            document.getElementById("host-hp-text").innerText = `${state.host_hp}/100`;
            document.getElementById("guest-hp-fill").style.width = `${state.guest_hp}%`;
            document.getElementById("guest-hp-text").innerText = `${state.guest_hp}/100`;

            const isHost = (myUserId === state.host_id);
            currentHandData = isHost ? state.host_hand : state.guest_hand;
            renderHand(currentHandData, state.status === "BATTLE");

            if (state.status === "BATTLE") {
                document.getElementById("setup-inputs").style.display = "none";
                document.getElementById("main-btn").style.display = "none";
                document.getElementById("submit-card-btn").style.display = "block";
            }
        }

        function renderHand(hand, isActive) {
            const handArea = document.getElementById("hand-area");
            if (!hand) return handArea.innerHTML = "";
            handArea.innerHTML = hand.map((card, idx) => `
                <div class="card-item ${selectedHandIndex === idx ? 'selected' : ''} ${!isActive ? 'disabled' : ''}" onclick="selectCard(${idx})">
                    <div style="font-size: 1.4rem;">${card.type === 'FIRE' ? '🔥' : card.type === 'WATER' ? '💧' : '🌲'}</div>
                    <div style="font-size: 0.8rem; font-weight:900; color:var(--neon-yellow);">ATK ${card.atk}</div>
                </div>
            `).join('');
        }

        function selectCard(index) {
            selectedHandIndex = index;
            document.getElementById("submit-card-btn").disabled = false;
            renderHand(currentHandData, true);
        }

        function submitCard() {
            if (selectedHandIndex === null || !ws) return;
            ws.send(JSON.stringify({ action: "SUBMIT_CARD", hand_index: selectedHandIndex }));
            document.getElementById("submit-card-btn").disabled = true;
        }
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ==========================================
# 2. ゲームロジック & WebSocket API
# ==========================================
class CreateRoomRequest(BaseModel):
    wallet_id: str
    bet_amount: int

class Card:
    def __init__(self, card_type: str, atk: int):
        self.type = card_type
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
        
        self.status = "WAITING"
        self.message = "対戦相手の参加を待っています..."
        self.host_hp = 100
        self.guest_hp = 100
        self.winner_id: Optional[str] = None
        
        self.host_hand: List[Card] = []
        self.guest_hand: List[Card] = []
        self.host_selected: Optional[Card] = None
        self.guest_selected: Optional[Card] = None
        
        self.lock = asyncio.Lock()
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

    new_bal = w_res.data[0]["balance"] - data.bet_amount
    await async_supabase_exec(supabase.table("wallets").update({"balance": new_bal}).eq("wallet_id", data.wallet_id))

    return {"room_id": room_id}

async def process_turn_battle(session: CardSession):
    h_card, g_card = session.host_selected, session.guest_selected
    h_dmg, g_dmg = h_card.atk, g_card.atk

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
