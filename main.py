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
from casino import router as casino_router
from inventory import router as inventory_router
from policy import router as policy_router
from fastapi.staticfiles import StaticFiles


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

class ReviewCreate(BaseModel):
    rating: int  # 1 〜 5
    comment: str = ""

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

@app.get("/casino", response_class=HTMLResponse)
def get_casino(request: Request):
    return templates.TemplateResponse(request=request, name="casino.html")

@app.get("/dice", response_class=HTMLResponse)
def get_dice(request: Request):
    return templates.TemplateResponse(request=request, name="dice.html")

@app.get("/inventory", response_class=HTMLResponse)
def get_inventory(request: Request):
    return templates.TemplateResponse(request=request, name="inventory.html")


@app.get("/admin/items", response_class=HTMLResponse)
def admin_items_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_items.html")

@app.get("/tower", response_class=HTMLResponse)
def get_tower(request: Request):
    return templates.TemplateResponse(request=request, name="tower.html")


app.mount("/templates", StaticFiles(directory="templates"), name="templates")

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
    
    if res.data and len(res.data) > 0:
        return res.data[0]
        
    return {
        "id": user.id, 
        "nickname": "名無しの労働奴隷", 
        "role": "slave",
        "agreed_terms_version": 0
    }


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
    today_str = str(date.today())

    try:
        supabase.rpc("claim_daily_tax", {
            "p_user_id": str(user.id),
            "p_wallet_id": str(data.wallet_id),
            "p_today": today_str
        }).execute()

        return {"message": "納税完了！100Gold獲得しました！"}
    except Exception as e:
        err_msg = getattr(e, "message", str(e))
        if "本日の受け取りは完了しています" in err_msg:
            raise HTTPException(status_code=400, detail="本日の納税は完了しています！")
        if "指定された口座が存在しません" in err_msg:
            raise HTTPException(status_code=400, detail="指定された受取口座が存在しないか、所有権がありません。")
        raise HTTPException(status_code=400, detail=f"納税処理エラー: {err_msg}")

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

# 1. 全契約一覧取得
@app.get("/api/contracts")
def get_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    res = supabase.table("contracts").select("*").order("created_at", desc=True).execute()
    contracts = res.data or []
    
    contract_ids = [c["id"] for c in contracts]
    reviews_map = {}
    if contract_ids:
        try:
            rev_res = supabase.table("contract_reviews").select("*").in_("contract_id", contract_ids).execute()
            for r in (rev_res.data or []):
                cid = r["contract_id"]
                if cid not in reviews_map:
                    reviews_map[cid] = []
                reviews_map[cid].append(r)
        except Exception:
            pass

    for c in contracts:
        c["reviews"] = reviews_map.get(c["id"], [])

    return {
        "contracts": contracts,
        "current_user_id": user.id,
        "is_king": is_king(user.id)
    }

# 2. マイ契約一覧取得（自分が依頼主または受注者の契約）
@app.get("/api/my-contracts")
def get_my_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    uid = user.id
    res = supabase.table("contracts").select("*")\
        .or_(f"creator_user_id.eq.{uid},acceptor_user_id.eq.{uid}")\
        .order("created_at", desc=True).execute()
    
    contracts = res.data or []
    contract_ids = [c["id"] for c in contracts]
    reviews_map = {}
    if contract_ids:
        try:
            rev_res = supabase.table("contract_reviews").select("*").in_("contract_id", contract_ids).execute()
            for r in (rev_res.data or []):
                cid = r["contract_id"]
                if cid not in reviews_map:
                    reviews_map[cid] = []
                reviews_map[cid].append(r)
        except Exception:
            pass

    for c in contracts:
        c["reviews"] = reviews_map.get(c["id"], [])

    return contracts

# 3. 契約書新規作成
@app.post("/api/contracts")
def create_contract(data: ContractCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    prof_res = supabase.table("profiles").select("nickname").eq("id", user.id).execute()
    nickname = prof_res.data[0]["nickname"] if prof_res.data else "名無しの労働奴隷"

    wallet_res = supabase.table("wallets").select("*").eq("wallet_id", data.creator_wallet_id).eq("user_id", user.id).execute()
    if not wallet_res.data:
        raise HTTPException(status_code=400, detail="指定された支払口座が存在しないか、所有権がありません。")

    wallet = wallet_res.data[0]
    if wallet["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています。")

    # 作成時点で金額をエスクロー引き落とし
    new_balance = wallet["balance"] - data.amount
    supabase.table("wallets").update({"balance": new_balance}).eq("id", wallet["id"]).execute()

    supabase.table("contracts").insert({
        "title": data.title,
        "description": data.description,
        "amount": data.amount,
        "creator_user_id": user.id,
        "creator_nickname": nickname,
        "creator_wallet_id": data.creator_wallet_id,
        "status": "OPEN"
    }).execute()

    return {"message": "自由市場に契約書を発行し、報酬を仮預かり（エスクロー）しました！"}

# 4. 契約受注
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

    w_res = supabase.table("wallets").select("*").eq("wallet_id", data.acceptor_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=400, detail="指定された受取口座が存在しないか、所有権がありません。")

    supabase.table("contracts").update({
        "acceptor_user_id": user.id,
        "acceptor_wallet_id": data.acceptor_wallet_id,
        "status": "SIGNED"
    }).eq("id", contract_id).execute()

    return {"message": "契約を受注しました！履行完了をお待ちください。"}

# 5. 契約キャンセル（募集中の取り消し＆返金）
@app.post("/api/contracts/{contract_id}/cancel")
def cancel_contract(contract_id: int, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    if contract["creator_user_id"] != user.id:
        raise HTTPException(status_code=403, detail="自分の作成した契約のみ取り消し可能です。")
    
    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="受注前の募集（OPEN）状態でのみ取り消しが可能です。")

    cr_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["creator_wallet_id"]).execute()
    if cr_w_res.data:
        cw = cr_w_res.data[0]
        supabase.table("wallets").update({"balance": cw["balance"] + contract["amount"]}).eq("id", cw["id"]).execute()

    supabase.table("contracts").update({"status": "CANCELLED"}).eq("id", contract_id).execute()

    return {"message": "契約を取り消し、仮預かり金を返金しました。"}

# 6. 契約完了承認＆報酬入金
@app.post("/api/contracts/{contract_id}/complete")
def complete_contract(contract_id: int, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    if contract["status"] != "SIGNED":
        raise HTTPException(status_code=400, detail="この契約は署名・履行待ち状態ではありません。")

    if contract["creator_user_id"] != user.id:
        raise HTTPException(status_code=403, detail="契約の完了承認は依頼主のみが行えます。")

    acceptor_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
    if not acceptor_w_res.data:
        raise HTTPException(status_code=400, detail="受注者の受取口座が見つかりません。")
    
    acceptor_wallet = acceptor_w_res.data[0]
    new_acceptor_balance = acceptor_wallet["balance"] + contract["amount"]
    supabase.table("wallets").update({"balance": new_acceptor_balance}).eq("id", acceptor_wallet["id"]).execute()

    supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()

    try:
        supabase.table("transfer_logs").insert({
            "sender_wallet_id": contract["creator_wallet_id"],
            "receiver_wallet_id": contract["acceptor_wallet_id"],
            "amount": contract["amount"]
        }).execute()
    except Exception:
        pass

    return {"message": "履行完了を承認しました！エスクローから報酬が受注者へ送金されました。"}

# 7. レビュー評価の投稿
@app.post("/api/contracts/{contract_id}/review")
def review_contract(contract_id: int, data: ReviewCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    if data.rating < 1 or data.rating > 5:
        raise HTTPException(status_code=400, detail="評価は1〜5の星で指定してください。")

    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません。")
    contract = c_res.data[0]

    if contract["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail="完了した契約のみ評価できます。")

    is_creator = contract["creator_user_id"] == user.id
    is_acceptor = contract["acceptor_user_id"] == user.id
    if not (is_creator or is_acceptor):
        raise HTTPException(status_code=403, detail="この契約の当事者のみ評価可能です。")

    target_user_id = contract["acceptor_user_id"] if is_creator else contract["creator_user_id"]

    try:
        supabase.table("contract_reviews").insert({
            "contract_id": contract_id,
            "reviewer_user_id": user.id,
            "target_user_id": target_user_id,
            "rating": data.rating,
            "comment": data.comment
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"評価登録エラー: {str(e)}")

    return {"message": "評価を投稿しました！"}

# 8. 国王専用介入コマンド
@app.post("/api/contracts/{contract_id}/king-override")
def king_override_contract(contract_id: int, action: dict, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    if not is_king(user.id):
        raise HTTPException(status_code=403, detail="権限がありません（国王専用コマンド）")

    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約書が見つかりません。")
    contract = c_res.data[0]

    mode = action.get("mode")

    if mode == "force_complete":
        if contract.get("acceptor_wallet_id"):
            acc_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
            if acc_w_res.data:
                aw = acc_w_res.data[0]
                supabase.table("wallets").update({"balance": aw["balance"] + contract["amount"]}).eq("id", aw["id"]).execute()
        supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()
        return {"message": "【国王裁定】強制的に契約を完了させ、受注者へ報酬を送金しました。"}

    elif mode == "force_cancel":
        cr_w_res = supabase.table("wallets").select("*").eq("wallet_id", contract["creator_wallet_id"]).execute()
        if cr_w_res.data:
            cw = cr_w_res.data[0]
            supabase.table("wallets").update({"balance": cw["balance"] + contract["amount"]}).eq("id", cw["id"]).execute()
        supabase.table("contracts").update({"status": "CANCELLED"}).eq("id", contract_id).execute()
        return {"message": "【国王裁定】強制的に契約を破棄し、エスクロー資金を依頼主に返金しました。"}

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

# --------------------------------------------------
# カジノモジュールの登録
# --------------------------------------------------
app.include_router(casino_router) 
app.include_router(inventory_router)
app.include_router(policy_router)
