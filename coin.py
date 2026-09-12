import os
import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

# 既存のdb.pyからのインポート想定
from db import get_supabase
from casino import get_user_from_token  # 共通関数を流用

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- リクエストモデル ---
class CoinBuyRequest(BaseModel):
    wallet_id: str
    amount: int  # 投資するGold額

class CoinSellRequest(BaseModel):
    wallet_id: str

# --- オンメモリ・ポジション管理 ---
# 構造: { user_id: { "wallet_id": str, "entry_price": float, "sol_amount": float, "bet_gold": int } }
COIN_POSITIONS = {}

# --- 外部API通信関数 ---
BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"

async def fetch_current_sol_price() -> float:
    """Binance APIから現在のSOL価格をサーバー側で取得する"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(BINANCE_API_URL)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
    except Exception as e:
        # API障害時は取引を一時停止させるための例外を投げる
        raise HTTPException(status_code=503, detail="市場データの取得に失敗しました。一時的に取引を停止しています。")

# --------------------------------------------------
# 画面配信ルート
# --------------------------------------------------
@router.get("/coin", response_class=HTMLResponse)
async def get_coin_page(request: Request):
    return templates.TemplateResponse(request=request, name="coin.html")

# --------------------------------------------------
# カオスコインAPI：購入 (Buy)
# --------------------------------------------------
@router.post("/api/coin/buy")
async def buy_coin(data: CoinBuyRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_id_str = str(user.id)
    supabase = await get_supabase()

    # 1. バリデーション
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="投資額は1Gold以上を指定してください。")
    if user_id_str in COIN_POSITIONS:
        raise HTTPException(status_code=400, detail="既にカオスコインを保有しています。先に売却してください。")

    # 2. 口座と残高の検証
    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    if wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 3. サーバー側で現在のSOL価格を確定
    current_price = await fetch_current_sol_price()

    # 4. 賭け金の引き落とし
    new_balance = wallet["balance"] - data.amount
    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    # 5. 保有ポジションの記録 (Gold額 ÷ SOL価格 = 保有SOL数)
    sol_amount = data.amount / current_price
    COIN_POSITIONS[user_id_str] = {
        "wallet_id": data.wallet_id,
        "entry_price": current_price,
        "sol_amount": sol_amount,
        "bet_gold": data.amount
    }

    return {
        "message": "購入完了",
        "entry_price": current_price,
        "sol_amount": sol_amount,
        "new_balance": new_balance
    }

# --------------------------------------------------
# カオスコインAPI：売却 (Sell)
# --------------------------------------------------
@router.post("/api/coin/sell")
async def sell_coin(data: CoinSellRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_id_str = str(user.id)
    supabase = await get_supabase()

    # 1. ポジションの確認
    if user_id_str not in COIN_POSITIONS:
        raise HTTPException(status_code=400, detail="保有しているカオスコインがありません。")
    
    position = COIN_POSITIONS[user_id_str]
    if position["wallet_id"] != data.wallet_id:
        raise HTTPException(status_code=400, detail="購入時と異なる口座での売却はできません。")

    # 2. サーバー側で現在のSOL価格を確定
    current_price = await fetch_current_sol_price()

    # 3. 最終金額の計算 (保有SOL数 × 現在のSOL価格)
    final_gold = int(position["sol_amount"] * current_price)

    # 4. 口座への反映
    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", position["wallet_id"]).execute()
    wallet = wallet_res.data[0]
    new_balance = wallet["balance"] + final_gold

    await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    # 5. ポジションの破棄
    del COIN_POSITIONS[user_id_str]

    return {
        "message": "売却完了",
        "exit_price": current_price,
        "pnl_gold": final_gold - position["bet_gold"],
        "payout_gold": final_gold,
        "new_balance": new_balance
    }
