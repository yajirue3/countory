# coin.py
import os
import httpx
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

from db import get_supabase
from casino import get_user_from_token

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

class CoinBuyRequest(BaseModel):
    wallet_id: str
    amount: int

class CoinSellRequest(BaseModel):
    wallet_id: str

BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"

async def fetch_current_sol_price() -> float:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(BINANCE_API_URL)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
    except Exception:
        raise HTTPException(status_code=503, detail="市場データの取得に失敗しました。一時的に取引を停止しています。")

@router.get("/coin", response_class=HTMLResponse)
async def get_coin_page(request: Request):
    return templates.TemplateResponse(request=request, name="coin.html")

@router.get("/api/coin/position")
async def get_coin_position(authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()
    
    try:
        res = await supabase.table("coin_positions").select("*").eq("user_id", user.id).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception:
        # DB未セットアップ時などの500エラークラッシュを防ぐ
        return None

@router.post("/api/coin/buy")
async def buy_coin(data: CoinBuyRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    
    if data.amount < 10:
        raise HTTPException(status_code=400, detail="投資額は10Gold以上を指定してください。")

    supabase = await get_supabase()
    current_price = await fetch_current_sol_price()
    sol_amount = float(data.amount) / current_price

    try:
        rpc_res = await supabase.rpc("buy_coin_position", {
            "p_user_id": str(user.id),
            "p_wallet_id": data.wallet_id,
            "p_bet_gold": data.amount,
            "p_current_price": current_price,
            "p_sol_amount": sol_amount
        }).execute()
        
        return {
            "message": "購入完了",
            "entry_price": current_price,
            "sol_amount": sol_amount
        }
    except Exception as e:
        err_msg = getattr(e, "message", str(e))
        raise HTTPException(status_code=400, detail=f"購入失敗: {err_msg}")

@router.post("/api/coin/sell")
async def sell_coin(data: CoinSellRequest, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    supabase = await get_supabase()
    current_price = await fetch_current_sol_price()

    try:
        rpc_res = await supabase.rpc("sell_coin_position", {
            "p_user_id": str(user.id),
            "p_wallet_id": data.wallet_id,
            "p_current_price": current_price
        }).execute()
        
        result_data = rpc_res.data
        return {
            "message": "売却完了",
            "exit_price": current_price,
            "pnl_gold": result_data["pnl_gold"],
            "payout_gold": result_data["payout_gold"]
        }
    except Exception as e:
        err_msg = getattr(e, "message", str(e))
        raise HTTPException(status_code=400, detail=f"売却失敗: {err_msg}")
