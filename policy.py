import os
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from supabase import create_client, Client

router = APIRouter()

# Supabaseクライアントの初期化
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --------------------------------------------------
# 規約設定
# --------------------------------------------------
CURRENT_TERMS_VERSION = 1

TERMS_TEXT = """
【村岡王国 利用規約】

1. サービスの目的
本サービスはエンターテインメントおよび技術検証を目的として提供されています。

2. ゲーム内通貨（Gold）について
ゲーム内で使用される「Gold」は架空のアプリ内通貨であり、現実の現金、金品、暗号資産等への換金・売買（RMT）は一切できません。

3. 禁止事項
ユーザーは以下の行為を行ってはなりません。
・リアルマネー取引（RMT）行為
・不正アクセス、通信の改ざん、およびバグの不正利用
・アカウントの不正作成・複数所持による報酬の不当取得（ただし3アカウントまでなら許可）
・学校などのふさわしくない場所や時間でのプレイ

4. 免責事項
・サーバーの障害、メンテナンス等によりデータが消失または不具合が生じた場合でも、運営者は補償の義務を負いません。
・ゲーム結果（勝敗・没収）に関する補償等には応じかねます。
・予告無しの規約の変更が起きる場合もあります。

5. アカウントの停止
本規約に違反した場合、然るべき処分を取る場合があります。
"""

# --------------------------------------------------
# リクエストモデル
# --------------------------------------------------
class TermsAgreeRequest(BaseModel):
    version: int


# トークンからユーザーを取得する共通関数
def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンが必要です。")
    token = authorization.split(" ")[1]
    
    user_res = supabase.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="無効なトークンです。")
    
    return user_res.user


# --------------------------------------------------
# APIエンドポイント (すべて同期 def で定義)
# --------------------------------------------------

# 最新の規約内容とバージョンを取得
@router.get("/api/policy/latest")
def get_latest_policy():
    return {
        "version": CURRENT_TERMS_VERSION,
        "content": TERMS_TEXT.strip()
    }


# ログイン中ユーザーの規約同意状態を取得
@router.get("/api/policy/status")
def get_policy_status(authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # profiles テーブルを参照
    res = supabase.table("profiles").select("agreed_terms_version").eq("id", user.id).execute()
    
    agreed_version = 0
    if res.data and len(res.data) > 0:
        val = res.data[0].get("agreed_terms_version")
        if val is not None:
            agreed_version = int(val)

    return {
        "current_version": CURRENT_TERMS_VERSION,
        "agreed_version": agreed_version,
        "needs_agreement": agreed_version < CURRENT_TERMS_VERSION
    }


# 規約に同意する
@router.post("/api/policy/agree")
def agree_policy(data: TermsAgreeRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    if data.version != CURRENT_TERMS_VERSION:
        raise HTTPException(status_code=400, detail="無効な規約バージョンです。")

    # profiles テーブルの同意済みバージョンを更新
    supabase.table("profiles").update({"agreed_terms_version": data.version}).eq("id", user.id).execute()

    return {
        "status": "success",
        "agreed_version": data.version
    }
