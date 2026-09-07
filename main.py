import os
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

class TransferRequest(BaseModel):
    receiver_nickname: str
    amount: int

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
# 画面配信（フロントエンド）
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
# 王国機能API
# --------------------------------------------------
@app.get("/api/profile")
def get_profile(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    res = supabase.table("profiles").select("*").eq("id", user.id).execute()
    if not res.data:
        new_prof = {"id": user.id, "nickname": "名無しの労働奴隷", "gold": 0}
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
def pay_tax(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    prof_res = supabase.table("profiles").select("*").eq("id", user.id).execute()
    
    if not prof_res.data:
        raise HTTPException(status_code=404, detail="プロフィールが見つかりません")
    
    profile = prof_res.data[0]
    today_str = str(date.today())

    if profile.get("last_tax_date") == today_str:
        raise HTTPException(status_code=400, detail="本日の納税は完了しています！")

    new_gold = (profile.get("gold") or 0) + 100
    supabase.table("profiles").update({
        "gold": new_gold,
        "last_tax_date": today_str
    }).eq("id", user.id).execute()

    return {"message": "納税完了！100ゴールドを獲得しました", "gold": new_gold}

# 送金処理API
@app.post("/api/transfer")
def transfer_gold(data: TransferRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    try:
        # SupabaseのRPC（Database Function）を呼び出し
        res = supabase.rpc("transfer_gold", {
            "sender_id": user.id,
            "receiver_nickname": data.receiver_nickname,
            "amount": data.amount
        }).execute()
        return {"message": f"{data.receiver_nickname} に {data.amount} Gold 送金しました！"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
