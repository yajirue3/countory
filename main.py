import os
import random
import string
from pathlib import Path
from datetime import date
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="村岡王国 ポータル")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class UserAuth(BaseModel):
    email: str
    password: str

class ProfileUpdate(BaseModel):
    nickname: str
    real_name: str

class ReportCreate(BaseModel):
    content: str

class WalletCreate(BaseModel):
    wallet_name: str

class PayTaxRequest(BaseModel):
    wallet_id: str

class TransferRequest(BaseModel):
    sender_wallet_id: str
    receiver_wallet_id: str
    amount: int

def generate_wallet_id():
    return "MW-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        user_res = supabase.auth.get_user(token)
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークンです")

def ensure_default_wallet(user_id: str):
    try:
        res = supabase.table("wallets").select("id").eq("user_id", user_id).execute()
        if not res.data:
            w_id = generate_wallet_id()
            supabase.table("wallets").insert({
                "wallet_id": w_id,
                "user_id": user_id,
                "wallet_name": "メイン口座",
                "balance": 0
            }).execute()
    except Exception as e:
        print(f"Default wallet creation error: {e}")

# --------------------------------------------------
# 画面配信
# --------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def get_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@app.get("/board", response_class=HTMLResponse)
def get_board(request: Request):
    return templates.TemplateResponse(request=request, name="board.html")

@app.get("/wallet", response_class=HTMLResponse)
def get_wallet(request: Request):
    return templates.TemplateResponse(request=request, name="wallet.html")

# --------------------------------------------------
# 認証API
# --------------------------------------------------
@app.post("/signup")
def signup(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase未設定")
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password})
        if res.user:
            supabase.table("profiles").insert({"id": res.user.id, "nickname": "名無しの労働奴隷"}).execute()
            ensure_default_wallet(res.user.id)
        return {"message": "国民登録が完了しました！"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login")
def login(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase未設定")
    try:
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        return {
            "message": "入国が許可されました！",
            "access_token": res.session.access_token,
            "email": user.email
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ログイン失敗: {str(e)}")

# --------------------------------------------------
# 王国API
# --------------------------------------------------
@app.get("/api/profile")
def get_profile(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    ensure_default_wallet(user.id)
    res = supabase.table("profiles").select("*").eq("id", user.id).execute()
    if not res.data:
        new_prof = {"id": user.id, "nickname": "名無しの労働奴隷"}
        supabase.table("profiles").insert(new_prof).execute()
        return new_prof
    return res.data[0]

@app.post("/api/profile")
def update_profile(data: ProfileUpdate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    supabase.table("profiles").update({
        "nickname": data.nickname,
        "real_name": data.real_name
    }).eq("id", user.id).execute()
    return {"message": "国民情報を更新しました"}

@app.post("/api/pay-tax")
def pay_tax(data: PayTaxRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    prof_res = supabase.table("profiles").select("*").eq("id", user.id).execute()
    today_str = str(date.today())

    if prof_res.data and prof_res.data[0].get("last_tax_date") == today_str:
        raise HTTPException(status_code=400, detail="本日の納税は完了しています！")

    wallet_res = supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された受取口座が存在しないか、所有権がありません。")

    target_wallet = wallet_res.data[0]
    current_balance = target_wallet.get("balance") or 0
    new_balance = current_balance + 100

    supabase.table("wallets").update({"balance": new_balance}).eq("id", target_wallet["id"]).execute()
    supabase.table("profiles").update({"last_tax_date": today_str}).eq("id", user.id).execute()

    return {"message": f"納税完了！「{target_wallet['wallet_name']}」（{target_wallet['wallet_id']}）に100Gold獲得！"}

@app.get("/api/wallets")
def get_wallets(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    ensure_default_wallet(user.id)
    res = supabase.table("wallets").select("*").eq("user_id", user.id).order("created_at").execute()
    return res.data

@app.post("/api/wallets")
def create_wallet(data: WalletCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    w_id = generate_wallet_id()
    try:
        supabase.table("wallets").insert({
            "wallet_id": w_id,
            "user_id": user.id,
            "wallet_name": data.wallet_name or "サブ口座",
            "balance": 0
        }).execute()
        return {"message": f"新規口座「{data.wallet_name}」を開設しました（ID: {w_id}）"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"口座開設エラー: {str(e)}")

# 送金処理＋履歴記録
@app.post("/api/transfer")
def transfer_gold(data: TransferRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    try:
        # 送金実行
        supabase.rpc("transfer_gold_by_wallet", {
            "sender_wallet_id": data.sender_wallet_id,
            "receiver_wallet_id": data.receiver_wallet_id,
            "amount": data.amount,
            "auth_user_id": user.id
        }).execute()

        # 送金履歴の保存
        supabase.table("transfer_logs").insert({
            "sender_wallet_id": data.sender_wallet_id,
            "receiver_wallet_id": data.receiver_wallet_id,
            "amount": data.amount
        }).execute()

        return {"message": f"口座 {data.receiver_wallet_id} へ {data.amount} Gold 送金しました！"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ログインユーザーが所有する口座に関わる送金履歴を取得
@app.get("/api/transfer-logs")
def get_transfer_logs(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    # 自分の所持ウォレットIDリストを取得
    my_wallets_res = supabase.table("wallets").select("wallet_id").eq("user_id", user.id).execute()
    my_wallet_ids = [w["wallet_id"] for w in my_wallets_res.data] if my_wallets_res.data else []

    if not my_wallet_ids:
        return []

    # 出金または入金に自分のウォレットIDが含まれるログを取得（直近20件）
    filter_str = f"sender_wallet_id.in.({','.join(my_wallet_ids)}),receiver_wallet_id.in.({','.join(my_wallet_ids)})"
    res = supabase.table("transfer_logs").select("*").or_(filter_str).order("created_at", desc=True).limit(20).execute()
    
    return {"logs": res.data, "my_wallets": my_wallet_ids}

@app.get("/api/reports")
def get_reports():
    res = supabase.table("reports").select("id, nickname, content, created_at").order("id", desc=True).limit(10).execute()
    return res.data

@app.post("/api/reports")
def create_report(data: ReportCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    prof_res = supabase.table("profiles").select("nickname").eq("id", user.id).execute()
    nickname = prof_res.data[0]["nickname"] if prof_res.data else "名無しの労働奴隷"

    supabase.table("reports").insert({
        "user_id": user.id,
        "nickname": nickname,
        "content": data.content
    }).execute()

    return {"message": "労働報告を提出しました"}
