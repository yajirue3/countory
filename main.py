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
# 王国API
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

@app.post("/api/transfer")
def transfer_gold(data: TransferRequest, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    try:
        supabase.rpc("transfer_gold_by_wallet", {
            "sender_wallet_id": data.sender_wallet_id,
            "receiver_wallet_id": data.receiver_wallet_id,
            "amount": data.amount,
            "auth_user_id": user.id
        }).execute()

        supabase.table("transfer_logs").insert({
            "sender_wallet_id": data.sender_wallet_id,
            "receiver_wallet_id": data.receiver_wallet_id,
            "amount": data.amount
        }).execute()

        return {"message": f"口座 {data.receiver_wallet_id} へ {data.amount} Gold 送金しました！"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/transfer-logs")
def get_transfer_logs(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    my_wallets_res = supabase.table("wallets").select("wallet_id").eq("user_id", user.id).execute()
    my_wallet_ids = [w["wallet_id"] for w in my_wallets_res.data] if my_wallets_res.data else []

    if not my_wallet_ids:
        return {"logs": [], "my_wallets": []}

    filter_str = f"sender_wallet_id.in.({','.join(my_wallet_ids)}),receiver_wallet_id.in.({','.join(my_wallet_ids)})"
    res = supabase.table("transfer_logs").select("*").or_(filter_str).order("created_at", desc=True).limit(20).execute()
    
    return {"logs": res.data, "my_wallets": my_wallet_ids}

# --------------------------------------------------
# 自由市場（Contracts）API
# --------------------------------------------------

# 1. 掲示板用：未受注（OPEN）の契約一覧を取得
@app.get("/api/contracts")
def get_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    res = supabase.table("contracts").select("*").eq("status", "OPEN").order("created_at", desc=True).execute()
    return {
        "contracts": res.data or [],
        "current_user_id": user.id,
        "is_king": is_king(user.id)
    }

# 2. マイ契約用：自分が関わっているすべての契約を取得
@app.get("/api/my-contracts")
def get_my_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    res = supabase.table("contracts").select("*").or_(
        f"creator_user_id.eq.{user.id},acceptor_user_id.eq.{user.id}"
    ).order("created_at", desc=True).execute()
    return res.data or []

# 3. 契約書の発行（発行時事前引き落とし・エスクロー化）
@app.post("/api/contracts")
def create_contract(data: ContractCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="報酬は1以上である必要があります。")

    prof_res = supabase.table("profiles").select("nickname").eq("id", user.id).execute()
    nickname = prof_res.data[0]["nickname"] if prof_res.data else "名無しの労働奴隷"

    # 支払指定口座の所有権＆残高チェック
    wallet_res = supabase.table("wallets").select("*").eq("wallet_id", data.creator_wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された支払口座が存在しないか、所有権がありません。")

    creator_wallet = wallet_res.data[0]
    if creator_wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="残高が不足しているため、契約書を発行できません。")

    # 発行時点で報酬を仮引き落とし（エスクロー預かり）
    new_balance = creator_wallet["balance"] - data.amount
    supabase.table("wallets").update({"balance": new_balance}).eq("id", creator_wallet["id"]).execute()

    supabase.table("contracts").insert({
        "title": data.title,
        "description": data.description,
        "amount": data.amount,
        "creator_user_id": user.id,
        "creator_nickname": nickname,
        "creator_wallet_id": data.creator_wallet_id,
        "status": "OPEN"
    }).execute()

    return {"message": "自由市場に契約書を発行しました（報酬額は預かり状態となりました）。"}

# 4. 契約の受注
@app.post("/api/contracts/{contract_id}/accept")
def accept_contract(contract_id: int, data: ContractAccept, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="この契約はすでに募集中ではありません。")

    if contract["creator_user_id"] == user.id:
        raise HTTPException(status_code=400, detail="自分が発行した契約を受注することはできません。")

    # 受注者の受取口座の所有権チェック
    w_res = supabase.table("wallets").select("*").eq("wallet_id", data.acceptor_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=400, detail="指定された受取口座が存在しないか、所有権がありません。")

    # ステータスを SIGNED に更新して受注確定
    supabase.table("contracts").update({
        "acceptor_user_id": user.id,
        "acceptor_wallet_id": data.acceptor_wallet_id,
        "status": "SIGNED"
    }).eq("id", contract_id).execute()

    return {"message": "契約を受注しました！依頼の完了報告を行ってください。"}

# 5. 履行完了承認
@app.post("/api/contracts/{contract_id}/complete")
def complete_contract(contract_id: int, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    if contract["status"] != "SIGNED":
        raise HTTPException(status_code=400, detail="この契約は署名・履行待ち状態ではありません。")

    # 依頼主のみが完了承認できる
    if contract["creator_user_id"] != user.id:
        raise HTTPException(status_code=403, detail="契約の完了承認は依頼主のみが行えます。")

    # 受注者の受取口座を探して報酬を入金
    acceptor_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
    if not acceptor_w_res.data:
        raise HTTPException(status_code=400, detail="受注者の受取口座が見つかりません。")
    
    acceptor_wallet = acceptor_w_res.data[0]
    new_acceptor_balance = acceptor_wallet["balance"] + contract["amount"]
    supabase.table("wallets").update({"balance": new_acceptor_balance}).eq("id", acceptor_wallet["id"]).execute()

    # ステータスを COMPLETED に更新
    supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()

    # 送金履歴に記録
    try:
        supabase.table("transfer_logs").insert({
            "sender_wallet_id": contract["creator_wallet_id"],
            "receiver_wallet_id": contract["acceptor_wallet_id"],
            "amount": contract["amount"]
        }).execute()
    except Exception:
        pass

    return {"message": "履行完了を承認しました！報酬が受注者へ送金されました。"}

# 6. 国王専用の介入権限API
@app.post("/api/contracts/{contract_id}/king-override")
def king_override_contract(contract_id: int, action: dict, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    if not is_king(user.id):
        raise HTTPException(status_code=403, detail="権限がありません（国王専用コマンド）")

    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    mode = action.get("mode") # "force_complete" または "force_cancel"

    if mode == "force_complete":
        if contract.get("acceptor_wallet_id"):
            acc_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
            if acc_w_res.data:
                aw = acc_w_res.data[0]
                supabase.table("wallets").update({"balance": aw["balance"] + contract["amount"]}).eq("id", aw["id"]).execute()
        supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()
        return {"message": "【国王裁定】強制的に契約を完了させ、受注者へ報酬を送金しました。"}

    elif mode == "force_cancel":
        # 返金処理（OPENまたはSIGNEDのいずれの場合もエスクロー資金を返金）
        cr_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["creator_wallet_id"]).execute()
        if cr_w_res.data:
            cw = cr_w_res.data[0]
            supabase.table("wallets").update({"balance": cw["balance"] + contract["amount"]}).eq("id", cw["id"]).execute()
            
        supabase.table("contracts").update({"status": "CANCELLED"}).eq("id", contract_id).execute()
        return {"message": "【国王裁定】強制的に契約を破棄し、預かり資金を依頼主に返金しました。"}

    raise HTTPException(status_code=400, detail="無効な裁定モードです。")

# --------------------------------------------------
# 掲示板API
# --------------------------------------------------
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
