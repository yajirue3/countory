from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
import random
import uuid

# db.py の get_supabase をインポート
from db import get_supabase

# ルーターの定義
router = APIRouter()

# テンプレートの設定
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --- リクエストモデル ---
class DicePlayRequest(BaseModel):
    wallet_id: str
    amount: int
    target: int
    mode: str  # "UNDER" または "OVER"

class TowerStartRequest(BaseModel):
    wallet_id: str
    amount: int

class TowerFinishRequest(BaseModel):
    wallet_id: str
    payout: int

class TowerStepRequest(BaseModel):
    game_id: str
    floor: int
    tile_index: int

class TowerCashoutRequest(BaseModel):
    game_id: str


# セッション保持用辞書 (メモリ管理)
TOWER_SESSIONS = {}


# 還元率 90.0% (ハウスエッジ 10.0%) の倍率計算関数
def get_tower_multiplier(floor: int) -> float:
    if floor <= 0:
        return 1.0
    return round((2.70) ** floor, 2)


# --- 共通関数：トークン検証 ---
async def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        supabase = await get_supabase()
        user_res = await supabase.auth.get_user(token)
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークンです")


# --------------------------------------------------
# カジノ画面配信ルート
# --------------------------------------------------
@router.get("/casino", response_class=HTMLResponse)
async def get_casino(request: Request):
    return templates.TemplateResponse(request=request, name="casino.html")

@router.get("/dice", response_class=HTMLResponse)
async def get_dice(request: Request):
    return templates.TemplateResponse(request=request, name="dice.html")

@router.get("/tower", response_class=HTMLResponse)
async def get_tower(request: Request):
    return templates.TemplateResponse(request=request, name="tower.html")


# --------------------------------------------------
# カジノAPI：ダイスゲーム実行
# --------------------------------------------------
@router.post("/api/dice/play")
async def play_dice(data: DicePlayRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    # 1. バリデーションチェック
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上を指定してください。")
    if data.target < 100 or data.target > 9500:
        raise HTTPException(status_code=400, detail="ターゲット値が不正です。")
    if data.mode not in ["UNDER", "OVER"]:
        raise HTTPException(status_code=400, detail="無効なゲームモードです。")

    # 2. 口座と残高の検証
    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    current_balance = wallet["balance"]

    if current_balance < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 3. 勝率と配当倍率（RTP 96.5% = ハウスエッジ3.5%）の計算
    if data.mode == "UNDER":
        win_chance = data.target / 10000.0
    else:  # OVER
        win_chance = (10000 - data.target) / 10000.0

    multiplier = 0.965 / win_chance  # 還元率96.5%に設定

    # 4. サーバー側で乱数生成 (0 〜 10000)
    roll_result = random.randint(0, 10000)

    # 5. 勝敗判定
    is_win = False
    if data.mode == "UNDER" and roll_result < data.target:
        is_win = True
    elif data.mode == "OVER" and roll_result > data.target:
        is_win = True

    # 6. 精算処理
    if is_win:
        payout = int(data.amount * multiplier)
        # 賭け金を引いて勝利金を加算
        new_balance = current_balance - data.amount + payout
    else:
        payout = 0
        # 賭け金を没収
        new_balance = current_balance - data.amount

    # 口座残高の更新
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    return {
        "roll": roll_result,
        "is_win": is_win,
        "payout": payout,
        "new_balance": new_balance,
        "multiplier": round(multiplier, 2)
    }


# --------------------------------------------------
# カジノAPI：タワーゲーム（イカサマ防止 & RTP 90.0%）
# --------------------------------------------------
@router.post("/api/tower/start")
async def start_tower(data: TowerStartRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上を指定してください。")

    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    if wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 賭け金を即時引き落とし
    new_balance = wallet["balance"] - data.amount
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    # 正解データをサーバー側でのみ保持 (レスポンスには含めない)
    safe_tiles = [random.randint(0, 2) for _ in range(15)]
    game_id = str(uuid.uuid4())

    TOWER_SESSIONS[game_id] = {
        "user_id": str(user.id),
        "wallet_id": data.wallet_id,
        "bet_amount": data.amount,
        "current_floor": 1,
        "safe_tiles": safe_tiles,
        "is_active": True
    }

    return {
        "game_id": game_id,
        "new_balance": new_balance
    }


@router.post("/api/tower/step")
async def step_tower(data: TowerStepRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    session = TOWER_SESSIONS.get(data.game_id)
    if not session or not session["is_active"]:
        raise HTTPException(status_code=400, detail="無効または終了したゲームセッションです。")
    if session["user_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="不正な操作です。")
    if data.floor != session["current_floor"]:
        raise HTTPException(status_code=400, detail="不正な階数指定です。")
    if data.tile_index not in [0, 1, 2]:
        raise HTTPException(status_code=400, detail="無効な選択肢です。")

    safe_tile = session["safe_tiles"][data.floor - 1]
    is_safe = (data.tile_index == safe_tile)

    if is_safe:
        multiplier = get_tower_multiplier(data.floor)
        current_payout = int(session["bet_amount"] * multiplier)

        # 15階全制覇時
        if data.floor == 15:
            session["is_active"] = False
            wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", session["wallet_id"]).execute()
            wallet = wallet_res.data[0]
            new_balance = wallet["balance"] + current_payout
            await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

            return {
                "is_safe": True,
                "safe_tile": safe_tile,
                "is_cleared": True,
                "multiplier": multiplier,
                "payout": current_payout,
                "new_balance": new_balance
            }
        else:
            session["current_floor"] += 1
            return {
                "is_safe": True,
                "safe_tile": safe_tile,
                "is_cleared": False,
                "multiplier": multiplier,
                "payout": current_payout,
                "next_floor": session["current_floor"]
            }
    else:
        # 罠を踏んでゲームオーバー
        session["is_active"] = False
        return {
            "is_safe": False,
            "safe_tile": safe_tile,
            "is_cleared": False,
            "multiplier": 0,
            "payout": 0
        }


@router.post("/api/tower/cashout")
async def cashout_tower(data: TowerCashoutRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    session = TOWER_SESSIONS.get(data.game_id)
    if not session or not session["is_active"]:
        raise HTTPException(status_code=400, detail="無効または終了したゲームセッションです。")
    if session["user_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="不正な操作です。")

    cleared_floor = session["current_floor"] - 1
    if cleared_floor < 1:
        raise HTTPException(status_code=400, detail="1階もクリアしていないため引き出せません。")

    multiplier = get_tower_multiplier(cleared_floor)
    payout = int(session["bet_amount"] * multiplier)

    session["is_active"] = False

    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", session["wallet_id"]).execute()
    wallet = wallet_res.data[0]
    new_balance = wallet["balance"] + payout
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    return {
        "payout": payout,
        "new_balance": new_balance
    }

# --- Slot用リクエストモデル ---
class SlotSpinRequest(BaseModel):
    wallet_id: str
    bet_amount: int

# --------------------------------------------------
# カジノ画面配信ルート：スロット
# --------------------------------------------------
@router.get("/slot", response_class=HTMLResponse)
async def get_slot(request: Request):
    return templates.TemplateResponse(request=request, name="slot.html")

# --------------------------------------------------
# カジノAPI：スロットゲーム（配当加算バグ修正版）
# --------------------------------------------------
@router.post("/api/slot/spin")
async def spin_slot(data: SlotSpinRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    if data.bet_amount < 1:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上を指定してください。")

    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    current_balance = wallet["balance"]

    if current_balance < data.bet_amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 1. 賭け金を即時引き落とし
    new_balance = current_balance - data.bet_amount
    
    # 2. 内部抽選 (配当額 payout は最初から整数 int で計算)
    rand_val = random.randint(0, 999)
    
    if rand_val < 10:    # 確率 1.0%
        prize = "BIG"
        payout = int(data.bet_amount * 50)   # 50倍
        result_symbols = ["7", "7", "7"]
    elif rand_val < 40:  # 確率 3.0%
        prize = "REG"
        payout = int(data.bet_amount * 10)   # 10倍
        result_symbols = ["BAR", "BAR", "BAR"]
    elif rand_val < 120: # 確率 8.0%
        prize = "BELL"
        payout = int(data.bet_amount * 3)    # 3倍
        result_symbols = ["BELL", "BELL", "BELL"]
    elif rand_val < 270: # 確率 15.0%
        prize = "GRAPE"
        payout = int(data.bet_amount * 1.5)  # 1.5倍 (切り捨て)
        result_symbols = ["GRAPE", "GRAPE", "GRAPE"]
    elif rand_val < 430: # 確率 16.0%
        prize = "REPLAY"
        payout = int(data.bet_amount * 1)    # 1倍
        if random.random() < 0.5:
            result_symbols = ["REPLAY", "REPLAY", "REPLAY"]
        else:
            result_symbols = ["CHERRY", random.choice(["BELL", "GRAPE", "REPLAY"]), random.choice(["BAR", "BELL", "GRAPE"])]
    else: 
        prize = "MISS"
        payout = 0
        pool = ["7", "BAR", "BELL", "GRAPE", "REPLAY"]
        result_symbols = [random.choice(pool) for _ in range(3)]
        
        # ハズレ補正処理
        if result_symbols[0] == result_symbols[1] == result_symbols[2]:
            others = [s for s in pool if s != result_symbols[1]]
            result_symbols[1] = random.choice(others)

    # 告知（ペカり）フラグ
    is_pekari = False
    is_early_pekari = False
    if prize in ["BIG", "REG"]:
        is_pekari = True
        if random.random() < 0.25: 
            is_early_pekari = True

    # 3. 配当を確実に残高へ加算
    if payout > 0:
        new_balance += payout
        
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    return {
        "prize": prize,
        "payout": payout,
        "result_symbols": result_symbols,
        "is_pekari": is_pekari,
        "is_early_pekari": is_early_pekari,
        "new_balance": new_balance
    }
    
# --- Mines用リクエストモデル ---
class MinesStartRequest(BaseModel):
    wallet_id: str
    amount: int
    mines_count: int

class MinesStepRequest(BaseModel):
    game_id: str
    tile_index: int

class MinesCashoutRequest(BaseModel):
    game_id: str


# セッション保持用辞書 (サーバーメモリ管理)
MINES_SESSIONS = {}


# 還元率 96.0% の倍率計算関数
def get_mines_multiplier(mines_count: int, revealed_count: int) -> float:
    if revealed_count <= 0:
        return 1.0
    safe_tiles = 25 - mines_count
    prob = 1.0
    for i in range(revealed_count):
        prob *= (safe_tiles - i) / (25 - i)
    return round(0.96 / prob, 2)


# --------------------------------------------------
# カジノAPI：マインズゲーム（不正対策・完全サーバー判定）
# --------------------------------------------------
@router.post("/api/mines/start")
async def start_mines(data: MinesStartRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上を指定してください。")
    if data.mines_count < 1 or data.mines_count > 24:
        raise HTTPException(status_code=400, detail="地雷の数は1〜24個の間で指定してください。")

    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    if wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 賭け金を即時引き落とし
    new_balance = wallet["balance"] - data.amount
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    # 地雷位置の抽選（クライアントには返さない）
    mine_positions = random.sample(range(25), data.mines_count)
    game_id = str(uuid.uuid4())

    MINES_SESSIONS[game_id] = {
        "user_id": str(user.id),
        "wallet_id": data.wallet_id,
        "wallet_db_id": wallet["id"],
        "bet_amount": data.amount,
        "mines_count": data.mines_count,
        "mine_positions": mine_positions,
        "revealed_tiles": [],
        "is_active": True,
        "processing": False
    }

    return {
        "game_id": game_id,
        "new_balance": new_balance,
        "mines_count": data.mines_count
    }


@router.post("/api/mines/step")
async def step_mines(data: MinesStepRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    session = MINES_SESSIONS.get(data.game_id)
    if not session or not session["is_active"]:
        raise HTTPException(status_code=400, detail="無効または終了したゲームセッションです。")
    if session["user_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="不正な操作です。")

    # 連打・並行リクエスト防止ロック
    if session.get("processing", False):
        raise HTTPException(status_code=429, detail="処理中です。")
    session["processing"] = True

    try:
        if data.tile_index < 0 or data.tile_index > 24:
            raise HTTPException(status_code=400, detail="不正なタイルの指定です。")
        if data.tile_index in session["revealed_tiles"]:
            raise HTTPException(status_code=400, detail="すでにオープンされたタイルです。")

        # 1. 地雷を踏んだ場合
        if data.tile_index in session["mine_positions"]:
            session["is_active"] = False
            mines = session["mine_positions"]
            MINES_SESSIONS.pop(data.game_id, None)

            return {
                "is_safe": False,
                "tile_index": data.tile_index,
                "mines": mines,
                "multiplier": 0.0,
                "payout": 0
            }

        # 2. 安全マスを開けた場合
        session["revealed_tiles"].append(data.tile_index)
        revealed_count = len(session["revealed_tiles"])
        max_safe = 25 - session["mines_count"]

        multiplier = get_mines_multiplier(session["mines_count"], revealed_count)
        current_payout = int(session["bet_amount"] * multiplier)

        # 3. 全安全マスを踏破（完全クリア）
        if revealed_count == max_safe:
            session["is_active"] = False

            wallet_res = await supabase.table("wallets").select("*").eq("id", session["wallet_db_id"]).execute()
            wallet = wallet_res.data[0]
            new_balance = wallet["balance"] + current_payout
            await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

            mines = session["mine_positions"]
            MINES_SESSIONS.pop(data.game_id, None)

            return {
                "is_safe": True,
                "tile_index": data.tile_index,
                "is_cleared": True,
                "multiplier": multiplier,
                "payout": current_payout,
                "new_balance": new_balance,
                "mines": mines
            }

        # 4. 途中経過
        return {
            "is_safe": True,
            "tile_index": data.tile_index,
            "is_cleared": False,
            "multiplier": multiplier,
            "current_payout": current_payout,
            "revealed_count": revealed_count
        }

    finally:
        if data.game_id in MINES_SESSIONS:
            MINES_SESSIONS[data.game_id]["processing"] = False


@router.post("/api/mines/cashout")
async def cashout_mines(data: MinesCashoutRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()

    session = MINES_SESSIONS.get(data.game_id)
    if not session or not session["is_active"]:
        raise HTTPException(status_code=400, detail="無効または終了したゲームセッションです。")
    if session["user_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="不正な操作です。")

    # DB処理の前に即時無効化（二重キャッシュアウト・連打バグの完全遮断）
    session["is_active"] = False

    revealed_count = len(session["revealed_tiles"])
    if revealed_count < 1:
        session["is_active"] = True
        raise HTTPException(status_code=400, detail="1マスも開けていないため引き出せません。")

    multiplier = get_mines_multiplier(session["mines_count"], revealed_count)
    payout = int(session["bet_amount"] * multiplier)

    # 配当加算
    wallet_res = await supabase.table("wallets").select("*").eq("id", session["wallet_db_id"]).execute()
    wallet = wallet_res.data[0]
    new_balance = wallet["balance"] + payout
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    mines = session["mine_positions"]
    MINES_SESSIONS.pop(data.game_id, None)

    return {
        "payout": payout,
        "multiplier": multiplier,
        "new_balance": new_balance,
        "mines": mines
    }
