import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

# --- Supabase 初期化 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL と SUPABASE_KEY の環境変数を設定してください。")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Muraoka Kingdom API")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# --- Pydantic リクエストモデル ---
class WalletCreate(BaseModel):
    wallet_name: str

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

class KingOverrideRequest(BaseModel):
    mode: str  # "force_complete" または "force_cancel"

class ReviewCreate(BaseModel):
    rating: int  # 1 〜 5
    comment: str = ""

class ReportCreate(BaseModel):
    target_user_id: str
    reason: str


# --- 認証依存関数 ---
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        user_res = supabase.auth.get_user(token)
        if not user_res or not user_res.user:
            raise HTTPException(status_code=401, detail="無効なトークンです")
        
        user_id = user_res.user.id
        prof_res = supabase.table("profiles").select("*").eq("id", user_id).execute()
        if not prof_res.data:
            raise HTTPException(status_code=404, detail="ユーザープロファイルが見つかりません")
        
        return prof_res.data[0]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"認証エラー: {str(e)}")


# ==========================================
# 1. ユーザー & ウォレット基本機能
# ==========================================

@app.get("/api/profile")
def get_profile(current_user: dict = Depends(get_current_user)):
    return current_user


@app.get("/api/wallets")
def get_wallets(current_user: dict = Depends(get_current_user)):
    res = supabase.table("wallets").select("*").eq("user_id", current_user["id"]).execute()
    return res.data or []


@app.post("/api/wallets")
def create_wallet(req: WalletCreate, current_user: dict = Depends(get_current_user)):
    new_wallet = {
        "user_id": current_user["id"],
        "wallet_name": req.wallet_name,
        "balance": 1000
    }
    res = supabase.table("wallets").insert(new_wallet).execute()
    return {"message": "口座を開設しました", "wallet": res.data[0]}


@app.post("/api/transfer")
def transfer_gold(req: TransferRequest, current_user: dict = Depends(get_current_user)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="送金額は1以上を指定してください")

    try:
        supabase.rpc("transfer_gold_by_wallet", {
            "sender_wallet_id": req.sender_wallet_id,
            "receiver_wallet_id": req.receiver_wallet_id,
            "amount": req.amount,
            "auth_user_id": current_user["id"]
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"送金失敗: {str(e)}")

    supabase.table("transfer_logs").insert({
        "sender_wallet_id": req.sender_wallet_id,
        "receiver_wallet_id": req.receiver_wallet_id,
        "amount": req.amount
    }).execute()

    return {"message": "送金が完了しました"}


# ==========================================
# 2. 自由市場 & エスクロー（GET系固定パスを先に定義）
# ==========================================

@app.get("/api/contracts")
def get_contracts(current_user: dict = Depends(get_current_user)):
    res = supabase.table("contracts").select("*").order("id", desc=True).execute()
    contracts = res.data or []
    
    contract_ids = [c["id"] for c in contracts]
    reviews_map = {}
    if contract_ids:
        rev_res = supabase.table("contract_reviews").select("*").in_("contract_id", contract_ids).execute()
        for r in (rev_res.data or []):
            cid = r["contract_id"]
            if cid not in reviews_map:
                reviews_map[cid] = []
            reviews_map[cid].append(r)

    for c in contracts:
        c["reviews"] = reviews_map.get(c["id"], [])

    is_king = current_user.get("role") == "king"
    return {
        "contracts": contracts,
        "current_user_id": current_user["id"],
        "is_king": is_king
    }


@app.get("/api/my-contracts")
def get_my_contracts(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    res = supabase.table("contracts").select("*")\
        .or_(f"creator_user_id.eq.{uid},acceptor_user_id.eq.{uid}")\
        .order("id", desc=True).execute()
    
    contracts = res.data or []
    contract_ids = [c["id"] for c in contracts]
    reviews_map = {}
    if contract_ids:
        rev_res = supabase.table("contract_reviews").select("*").in_("contract_id", contract_ids).execute()
        for r in (rev_res.data or []):
            cid = r["contract_id"]
            if cid not in reviews_map:
                reviews_map[cid] = []
            reviews_map[cid].append(r)

    for c in contracts:
        c["reviews"] = reviews_map.get(c["id"], [])

    return contracts


@app.post("/api/contracts")
def create_contract(req: ContractCreate, current_user: dict = Depends(get_current_user)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="金額は1以上で指定してください")

    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.creator_wallet_id).execute()
    if not w_res.data:
        raise HTTPException(status_code=404, detail="指定された支払口座が存在しません")
    
    wallet = w_res.data[0]
    if wallet["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="自分の口座のみ指定できます")
    
    if wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="口座の残高が不足しています")

    # 1. エスクロー引き落とし
    new_balance = wallet["balance"] - req.amount
    supabase.table("wallets").update({"balance": new_balance}).eq("wallet_id", req.creator_wallet_id).execute()

    # 2. 契約作成
    new_contract = {
        "title": req.title,
        "description": req.description,
        "amount": req.amount,
        "creator_user_id": current_user["id"],
        "creator_nickname": current_user.get("nickname", "名無し"),
        "creator_wallet_id": req.creator_wallet_id,
        "status": "OPEN"
    }
    c_res = supabase.table("contracts").insert(new_contract).execute()

    supabase.table("transfer_logs").insert({
        "sender_wallet_id": req.creator_wallet_id,
        "receiver_wallet_id": "ESCROW_SYSTEM",
        "amount": req.amount
    }).execute()

    return {"message": "契約を作成し、報酬を仮預かりしました", "contract": c_res.data[0]}


# --- 動的IDを含むパス ({contract_id}) はここにまとめる ---

@app.post("/api/contracts/{contract_id}/accept")
def accept_contract(contract_id: int, req: ContractAccept, current_user: dict = Depends(get_current_user)):
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません")
    contract = c_res.data[0]

    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="募集中の契約のみ受注できます")
    if contract["creator_user_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="自分の契約は受注できません")

    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.acceptor_wallet_id).execute()
    if not w_res.data or w_res.data[0]["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="無効な受取口座です")

    supabase.table("contracts").update({
        "status": "SIGNED",
        "acceptor_user_id": current_user["id"],
        "acceptor_wallet_id": req.acceptor_wallet_id
    }).eq("id", contract_id).execute()

    return {"message": "契約を受注しました！"}


@app.post("/api/contracts/{contract_id}/cancel")
def cancel_contract(contract_id: int, current_user: dict = Depends(get_current_user)):
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません")
    contract = c_res.data[0]

    if contract["creator_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="自分の作成した契約のみキャンセル可能です")
    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="受注前（OPEN）の契約のみキャンセル可能です")

    w_res = supabase.table("wallets").select("balance").eq("wallet_id", contract["creator_wallet_id"]).execute()
    if w_res.data:
        curr_bal = w_res.data[0]["balance"]
        supabase.table("wallets").update({"balance": curr_bal + contract["amount"]}).eq("wallet_id", contract["creator_wallet_id"]).execute()

    supabase.table("contracts").update({"status": "CANCELLED"}).eq("id", contract_id).execute()

    supabase.table("transfer_logs").insert({
        "sender_wallet_id": "ESCROW_SYSTEM",
        "receiver_wallet_id": contract["creator_wallet_id"],
        "amount": contract["amount"]
    }).execute()

    return {"message": "契約を取り消し、仮預かり金を返金しました"}


@app.post("/api/contracts/{contract_id}/complete")
def complete_contract(contract_id: int, current_user: dict = Depends(get_current_user)):
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません")
    contract = c_res.data[0]

    if contract["creator_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="依頼主（作成者）のみが完了承認できます")
    if contract["status"] != "SIGNED":
        raise HTTPException(status_code=400, detail="履行中（SIGNED）の契約のみ承認可能です")

    a_wallet_res = supabase.table("wallets").select("balance").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
    if not a_wallet_res.data:
        raise HTTPException(status_code=404, detail="受注者の口座が見つかりません")
    
    a_balance = a_wallet_res.data[0]["balance"]
    supabase.table("wallets").update({"balance": a_balance + contract["amount"]}).eq("wallet_id", contract["acceptor_wallet_id"]).execute()
    supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()

    supabase.table("transfer_logs").insert({
        "sender_wallet_id": "ESCROW_SYSTEM",
        "receiver_wallet_id": contract["acceptor_wallet_id"],
        "amount": contract["amount"]
    }).execute()

    return {"message": "履行完了を承認し、受注者へ送金しました！"}


@app.post("/api/contracts/{contract_id}/review")
def review_contract(contract_id: int, req: ReviewCreate, current_user: dict = Depends(get_current_user)):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="評価は1〜5の間で指定してください")

    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません")
    contract = c_res.data[0]

    if contract["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail="完了した契約のみ評価できます")

    is_creator = contract["creator_user_id"] == current_user["id"]
    is_acceptor = contract["acceptor_user_id"] == current_user["id"]
    if not (is_creator or is_acceptor):
        raise HTTPException(status_code=403, detail="この契約の当事者のみ評価可能です")

    target_user_id = contract["acceptor_user_id"] if is_creator else contract["creator_user_id"]

    rev_check = supabase.table("contract_reviews")\
        .select("*")\
        .eq("contract_id", contract_id)\
        .eq("reviewer_user_id", current_user["id"])\
        .execute()
    
    if rev_check.data:
        raise HTTPException(status_code=400, detail="この契約は既に評価済みです")

    supabase.table("contract_reviews").insert({
        "contract_id": contract_id,
        "reviewer_user_id": current_user["id"],
        "target_user_id": target_user_id,
        "rating": req.rating,
        "comment": req.comment
    }).execute()

    return {"message": "評価を送信しました！"}


@app.post("/api/contracts/{contract_id}/king-override")
def king_override(contract_id: int, req: KingOverrideRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "king":
        raise HTTPException(status_code=403, detail="国王のみが実行可能な権限です")

    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が見つかりません")
    contract = c_res.data[0]

    if contract["status"] in ["COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=400, detail="既に終了した契約です")

    if req.mode == "force_complete":
        if not contract["acceptor_wallet_id"]:
            raise HTTPException(status_code=400, detail="受注者が未確定の契約は強制完了できません")
        
        a_w = supabase.table("wallets").select("balance").eq("wallet_id", contract["acceptor_wallet_id"]).execute()
        if a_w.data:
            supabase.table("wallets").update({"balance": a_w.data[0]["balance"] + contract["amount"]}).eq("wallet_id", contract["acceptor_wallet_id"]).execute()
        
        supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()
        msg = "👑 国王裁定: 契約を【強制完了】し、受注者へ送金しました"

    elif req.mode == "force_cancel":
        c_w = supabase.table("wallets").select("balance").eq("wallet_id", contract["creator_wallet_id"]).execute()
        if c_w.data:
            supabase.table("wallets").update({"balance": c_w.data[0]["balance"] + contract["amount"]}).eq("wallet_id", contract["creator_wallet_id"]).execute()
        
        supabase.table("contracts").update({"status": "CANCELLED"}).eq("id", contract_id).execute()
        msg = "👑 国王裁定: 契約を【強制破棄】し、依頼主へ全額返金しました"
    else:
        raise HTTPException(status_code=400, detail="無効なモードです")

    return {"message": msg}


# ==========================================
# 3. 国王権限・通報・ログ監視機能
# ==========================================

@app.get("/api/reports")
def get_reports(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "king":
        raise HTTPException(status_code=403, detail="国王のみ閲覧可能です")
    res = supabase.table("reports").select("*").order("id", desc=True).execute()
    return res.data or []


@app.post("/api/reports")
def create_report(req: ReportCreate, current_user: dict = Depends(get_current_user)):
    new_report = {
        "reporter_user_id": current_user["id"],
        "target_user_id": req.target_user_id,
        "reason": req.reason
    }
    res = supabase.table("reports").insert(new_report).execute()
    return {"message": "密告（通報）を受理しました。国王の裁定をお待ちください。"}


@app.get("/api/logs")
def get_transfer_logs(current_user: dict = Depends(get_current_user)):
    res = supabase.table("transfer_logs").select("*").order("id", desc=True).limit(50).execute()
    return res.data or []
