import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="Web Application")

# 実行ファイル(main.py)のあるディレクトリからの絶対パスでtemplatesを指定
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 環境変数からSupabaseの接続情報を取得
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Supabaseクライアントの初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class UserAuth(BaseModel):
    email: str
    password: str

# --------------------------------------------------
# フロントエンド（専用HTMLの配信）
# --------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def get_index(request: Request):
    # 最新のFastAPI/Starlette仕様に対応した書き方に修正
    return templates.TemplateResponse(request=request, name="index.html")

# --------------------------------------------------
# バックエンドAPI（認証ロジック）
# --------------------------------------------------
@app.post("/signup")
def signup(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabaseクライアントが未設定です")
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password})
        return {"message": "ユーザー登録が完了しました！"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login")
def login(user: UserAuth):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabaseクライアントが未設定です")
    try:
        res = supabase.auth.sign_in_with_password({"email": user.email, "password": user.password})
        return {"message": "ログインに成功しました！", "access_token": res.session.access_token}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ログイン失敗: {str(e)}")
