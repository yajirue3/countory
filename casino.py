from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
import random
import os
from supabase import create_client, Client

# ルーターの定義
router = APIRouter()

# テンプレートの設定
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Supabaseクライアントの初期化
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


# --- リクエストモデル ---
class DicePlayRequest(BaseModel):
    wallet_id: str
    amount: int
    target: int
    mode: str  # "UNDER" または "OVER"


# --- 共通関数：トークン検証 ---
def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        user_res = supabase.auth.get_user(token)
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークンです")


# --------------------------------------------------
# カジノ画面配信ルート
# --------------------------------------------------
@router.get("/casino", response_class=HTMLResponse)
def get_casino(request: Request):
    return templates.TemplateResponse(request=request, name="casino.html")

@router.get("/dice", response_class=HTMLResponse)
def get_dice(request: Request):
    return templates.TemplateResponse(request=request, name="dice.html")


# --------------------------------------------------
# カジノAPI：ダイスゲーム実行
# --------------------------------------------------
@router.post("/api/dice/play")
def play_dice(data: DicePlayRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # 1. バリデーションチェック
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="賭け金は1Gold以上を指定してください。")
    if data.target < 100 or data.target > 9500:
        raise HTTPException(status_code=400, detail="ターゲット値が不正です。")
    if data.mode not in ["UNDER", "OVER"]:
        raise HTTPException(status_code=400, detail="無効なゲームモードです。")

    # 2. 口座と残高の検証
    wallet_res = supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    current_balance = wallet["balance"]

    if current_balance < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 3. 勝率と配当倍率（RTP 90% = ハウスエッジ10%）の計算
    if data.mode == "UNDER":
        win_chance = data.target / 10000.0
    else:  # OVER
        win_chance = (10000 - data.target) / 10000.0

    multiplier = 0.90 / win_chance  # 還元率90%（プレイヤー有利にならない）

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
    supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    return {
        "roll": roll_result,
        "is_win": is_win,
        "payout": payout,
        "new_balance": new_balance,
        "multiplier": round(multiplier, 2)
    }
