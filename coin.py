import os
import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

# 既存のdb.pyからのインポート想定
from db import get_supabase
from casino import get_user_from_token

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# --- リクエストモデル ---
class CoinBuyRequest(BaseModel):
    wallet_id: str
    amount: int

class CoinSellRequest(BaseModel):
    wallet_id: str

# --- オンメモリ・ポジション管理 ---
# 【重要】本番環境でマルチプロセス(Uvicorn workers > 1)を使用する場合は、
# この辞書をSupabaseの `coin_positions` テーブル等に移行する必要があります。
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
    except Exception:
        raise HTTPException(status_code=503, detail="市場データの取得に失敗しました。一時的に取引を停止しています。")

# --------------------------------------------------
# 画面配信ルート
# --------------------------------------------------
@router.get("/coin", response_class=HTMLResponse)
async def get_coin_page(request: Request):
    return templates.TemplateResponse(request=request, name="coin.html")

# --------------------------------------------------
# SOLトレードAPI：購入 (Buy)
# --------------------------------------------------
@router.post("/api/coin/buy")
async def buy_coin(data: CoinBuyRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_id_str = str(user.id)
    
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="投資額は1Gold以上を指定してください。")
    if user_id_str in COIN_POSITIONS:
        raise HTTPException(status_code=400, detail="既にポジションを保有しています。先に決済してください。")

    supabase = await get_supabase()

    # 所有権と残高の厳格な検証 (user_id一致を強制)
    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=403, detail="指定された口座が存在しないか、アクセス権がありません。")

    wallet = wallet_res.data[0]
    if wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    current_price = await fetch_current_sol_price()

    # 残高の引き落とし (本来はRPCによるアトミック更新を推奨)
    new_balance = wallet["balance"] - data.amount
    update_res = await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()
    
    if not update_res.data:
        raise HTTPException(status_code=500, detail="残高の引き落とし処理に失敗しました。")

    # ポジションの記録
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
# SOLトレードAPI：売却 (Sell)
# --------------------------------------------------
@router.post("/api/coin/sell")
async def sell_coin(data: CoinSellRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_id_str = str(user.id)
    
    if user_id_str not in COIN_POSITIONS:
        raise HTTPException(status_code=400, detail="保有しているポジションがありません。")
    
    position = COIN_POSITIONS[user_id_str]
    if position["wallet_id"] != data.wallet_id:
        raise HTTPException(status_code=400, detail="購入時と異なる口座での売却はできません。")

    supabase = await get_supabase()

    # 【ゼロトラスト修正】売却時も必ず user_id を検証し、他人口座への不正送金を防止
    wallet_res = await supabase.table("wallets").select("*").eq("wallet_id", position["wallet_id"]).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=403, detail="決済先口座の認証に失敗しました。")

    wallet = wallet_res.data[0]
    current_price = await fetch_current_sol_price()

    # 最終金額の計算と口座への反映
    final_gold = int(position["sol_amount"] * current_price)
    new_balance = wallet["balance"] + final_gold

    update_res = await supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()
    
    if not update_res.data:
        raise HTTPException(status_code=500, detail="決済金の振り込みに失敗しました。")

    # 決済完了後にポジション破棄
    del COIN_POSITIONS[user_id_str]

    return {
        "message": "売却完了",
        "exit_price": current_price,
        "pnl_gold": final_gold - position["bet_gold"],
        "payout_gold": final_gold,
        "new_balance": new_balance
    }
