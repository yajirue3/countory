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

class ContractCreate(BaseModel):
    title: str
    description: str
    amount: int
    creator_wallet_id: str

class ContractAccept(BaseModel):
    acceptor_wallet_id: str

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

def is_king(user_id: str) -> bool:
    try:
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
        if res.data and res.data[0].get("role") == "king":
            return True
    except Exception:
        pass
    return False

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

@app.get("/market", response_class=HTMLResponse)
def get_market(request: Request):
    return templates.TemplateResponse(request=request, name="market.html")

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
            supabase.table("profiles").insert({"id": res.user.id, "nickname": "名無しの労働奴隷", "role": "slave"}).execute()
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
# 王国API & プロファイル
# --------------------------------------------------
@app.get("/api/profile")
def get_profile(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    ensure_default_wallet(user.id)
    res = supabase.table("profiles").select("*").eq("id", user.id).execute()
    if not res.data:
        new_prof = {"id": user.id, "nickname": "名無しの労働奴隷", "role": "slave"}
        supabase.table("profiles").insert(new_prof).execute()
        return new_prof
    return res.data[0]

# --------------------------------------------------
# 自由市場 (エスクロー契約) API
# --------------------------------------------------

# 1. 契約一覧（OPENな公開契約のみ取得 -> 当事者以外から非表示化）
@app.get("/api/market/contracts")
def get_market_contracts():
    res = supabase.table("contracts").select("*").eq("status", "OPEN").execute()
    return res.data

# 自分の関わっている契約一覧を取得（ダッシュボード・進行中表示用）
@app.get("/api/market/my-contracts")
def get_my_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    # ユーザー所有のウォレットを取得
    wallets_res = supabase.table("wallets").select("wallet_id").eq("user_id", user.id).execute()
    wallet_ids = [w["wallet_id"] for w in wallets_res.data]
    
    if not wallet_ids:
        return []

    # 自分が作成者か受注者である契約をすべて取得
    res = supabase.table("contracts").select("*").or_(
        f"creator_wallet_id.in.({','.join(wallet_ids)}),acceptor_wallet_id.in.({','.join(wallet_ids)})"
    ).execute()
    return res.data

# 2. 契約書の掲示（作成時の残高チェック付き）
@app.post("/api/market/contracts")
def create_contract(req: ContractCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="金額は1以上である必要があります")

    # 指定ウォレットの所有権と残高チェック
    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.creator_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=403, detail="無効なウォレットです")
    
    wallet = w_res.data[0]
    if wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="残高が不足しているため契約書を掲示できません")

    # 先に資金を引き落としてエスクロー預かり状態にする
    new_balance = wallet["balance"] - req.amount
    supabase.table("wallets").update({"balance": new_balance}).eq("wallet_id", req.creator_wallet_id).execute()

    # 契約の登録
    contract_data = {
        "title": req.title,
        "description": req.description,
        "amount": req.amount,
        "creator_wallet_id": req.creator_wallet_id,
        "status": "OPEN"
    }
    res = supabase.table("contracts").insert(contract_data).execute()
    return {"message": "契約書を市場に掲示しました", "contract": res.data[0]}

# 3. 契約の受注（排他制御）
@app.post("/api/market/contracts/{contract_id}/accept")
def accept_contract(contract_id: str, req: ContractAccept, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # 受注用ウォレットの所有権チェック
    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.acceptor_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=403, detail="無効なウォレットです")

    # 対象契約のステータスチェック（OPENかどうかの検証）
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が存在しません")
    
    contract = c_res.data[0]
    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="この契約は既に他のユーザーに受注されたか、終了しています")

    if contract["creator_wallet_id"] == req.acceptor_wallet_id:
        raise HTTPException(status_code=400, detail="自分の作成した契約を受注することはできません")

    # ステータスを IN_PROGRESS に更新し、受任ウォレットを記録（これで他人の一覧から消える）
    update_res = supabase.table("contracts").update({
        "status": "IN_PROGRESS",
        "acceptor_wallet_id": req.acceptor_wallet_id
    }).eq("id", contract_id).execute()

    return {"message": "契約を受注しました", "contract": update_res.data[0]}

# 4. 依頼完了処理（報酬支払いとステータス更新）
@app.post("/api/market/contracts/{contract_id}/complete")
def complete_contract(contract_id: str, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # 契約の取得
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が存在しません")
    
    contract = c_res.data[0]
    if contract["status"] != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail="進行中の契約のみ完了できます")

    # 発注者のウォレット所有権チェック（依頼完了・承認権限は作成者にあるものとする）
    creator_w = supabase.table("wallets").select("*").eq("wallet_id", contract["creator_wallet_id"]).eq("user_id", user.id).execute()
    if not creator_w.data:
        raise HTTPException(status_code=403, detail="この契約を完了させる権限がありません")

    acceptor_wallet_id = contract["acceptor_wallet_id"]
    reward_amount = contract["amount"]

    # 受注者のウォレット残高を加算
    acceptor_w = supabase.table("wallets").select("balance").eq("wallet_id", acceptor_wallet_id).execute()
    if not acceptor_w.data:
        raise HTTPException(status_code=400, detail="受注者のウォレットが見つかりません")

    new_acceptor_balance = acceptor_w.data[0]["balance"] + reward_amount
    supabase.table("wallets").update({"balance": new_acceptor_balance}).eq("wallet_id", acceptor_wallet_id).execute()

    # ステータスを COMPLETED に変更
    supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()

    return {"message": "依頼が完了し、報酬が支払われました"}
