from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
import random
import os
import uuid
from supabase import create_async_client, AsyncClient

# ルーターの定義
router = APIRouter()

# テンプレートの設定
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Supabaseクライアントの初期化
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: AsyncClient = create_async_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


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
