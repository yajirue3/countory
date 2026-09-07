import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="Web Application")

# 環境変数からSupabaseの接続情報を取得
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Supabaseクライアントの初期化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

class UserAuth(BaseModel):
    email: str
    password: str

# --------------------------------------------------
# フロントエンド（HTML / CSS / JS）の配信
# --------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def get_index():
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>アカウント認証</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
            .card { background: #ffffff; padding: 40px; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
            .tabs { display: flex; margin-bottom: 24px; border-bottom: 2px solid #e4e6eb; }
            .tab { flex: 1; padding: 12px; text-align: center; font-weight: bold; color: #65676b; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; }
            .tab.active { color: #1877f2; border-bottom-color: #1877f2; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; color: #050505; font-size: 14px; font-weight: 600; }
            input { width: 100%; padding: 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 15px; outline: none; transition: border-color 0.2s; }
            input:focus { border-color: #1877f2; }
            button { width: 100%; padding: 12px; background: #1877f2; color: white; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
            button:hover { background: #166fe5; }
            .message { margin-top: 16px; padding: 10px; border-radius: 6px; font-size: 14px; display: none; text-align: center; }
            .message.success { background: #e7f3ff; color: #1877f2; display: block; }
            .message.error { background: #ffebe9; color: #dc3545; display: block; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="tabs">
                <div class="tab active" id="tab-login" onclick="switchTab('login')">ログイン</div>
                <div class="tab" id="tab-signup" onclick="switchTab('signup')">新規登録</div>
            </div>
            <form id="auth-form" onsubmit="handleSubmit(event)">
                <div class="form-group">
                    <label>メールアドレス</label>
                    <input type="email" id="email" required placeholder="example@email.com">
                </div>
                <div class="form-group">
                    <label>パスワード</label>
                    <input type="password" id="password" required placeholder="••••••••">
                </div>
                <button type="submit" id="btn-submit">ログイン</button>
            </form>
            <div id="message" class="message"></div>
        </div>

        <script>
            let currentMode = 'login';

            function switchTab(mode) {
                currentMode = mode;
                document.getElementById('tab-login').classList.toggle('active', mode === 'login');
                document.getElementById('tab-signup').classList.toggle('active', mode === 'signup');
                document.getElementById('btn-submit').textContent = mode === 'login' ? 'ログイン' : '新規登録';
                document.getElementById('message').className = 'message';
            }

            async function handleSubmit(event) {
                event.preventDefault();
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const msgBox = document.getElementById('message');
                msgBox.className = 'message';

                try {
                    const response = await fetch('/' + currentMode, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password })
                    });
                    const data = await response.json();

                    if (response.ok) {
                        msgBox.className = 'message success';
                        msgBox.textContent = data.message || '成功しました！';
                        if (data.access_token) {
                            localStorage.setItem('token', data.access_token);
                        }
                    } else {
                        msgBox.className = 'message error';
                        msgBox.textContent = data.detail || 'エラーが発生しました。';
                    }
                } catch (err) {
                    msgBox.className = 'message error';
                    msgBox.textContent = '通信エラーが発生しました。';
                }
            }
        </script>
    </body>
    </html>
    """

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
