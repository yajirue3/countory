import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="FastAPI Auth System")

# 環境変数からSupabaseの接続情報を取得
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Supabaseクライアントの初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# リクエストのデータ構造定義
class UserAuth(BaseModel):
    email: str
    password: str

@app.get("/")
def read_root():
    return {"status": "ok", "message": "FastAPI on Render with Supabase is running!"}

# サインアップ（新規登録）API
@app.post("/signup")
def signup(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase client not configured")
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password})
        return {"message": "ユーザー登録リクエスト成功。確認メールを送信しました。", "user": res.user}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ログインAPI
@app.post("/login")
def login(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase client not configured")
    try:
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        return {"message": "ログイン成功", "access_token": res.session.access_token}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ログイン失敗: {str(e)}")
