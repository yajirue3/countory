import os
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from supabase import create_client, Client

router = APIRouter(prefix="/api", tags=["inventory"])


# --- リクエストモデル ---
class ItemCreateUpdate(BaseModel):
    item_id: str
    name: str
    description: Optional[str] = ""
    base_price: int

class SellItemRequest(BaseModel):
    item_id: str
    quantity: int
    wallet_id: str

class TransferItemRequest(BaseModel):
    item_id: str
    quantity: int
    target_email: str


# --- Supabaseクライアントおよび認証処理（main.pyに依存しない単体実装） ---
def get_supabase() -> Client:
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase環境変数が設定されていません")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_current_user_from_header(authorization: str = Header(None)) -> Any:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    supabase = get_supabase()
    try:
        user_res = supabase.auth.get_user(token)
        if not user_res.user:
            raise HTTPException(status_code=401, detail="無効なトークンです")
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="トークンの検証に失敗しました")

def verify_king_user(authorization: str = Header(None)) -> Any:
    user = get_current_user_from_header(authorization)
    supabase = get_supabase()
    try:
        res = supabase.table("profiles").select("role").eq("id", user.id).execute()
        if not res.data or res.data[0].get("role") != "king":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="国王専用の操作です"
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="権限確認処理でエラーが発生しました"
        )
    return user


# ==========================================
# 👑 国王専用：アイテムマスター管理 API
# ==========================================

@router.get("/admin/items")
def get_admin_items(current_user: Any = Depends(verify_king_user)):
    supabase = get_supabase()
    res = supabase.table("items").select("*").order("created_at").execute()
    return res.data

@router.post("/admin/items")
def upsert_admin_item(item: ItemCreateUpdate, current_user: Any = Depends(verify_king_user)):
    supabase = get_supabase()
    data = {
        "item_id": item.item_id,
        "name": item.name,
        "description": item.description,
        "base_price": item.base_price
    }
    res = supabase.table("items").upsert(data).execute()
    return {"message": "アイテム情報を更新しました", "data": res.data}

@router.delete("/admin/items/{item_id}")
def delete_admin_item(item_id: str, current_user: Any = Depends(verify_king_user)):
    supabase = get_supabase()
    supabase.table("items").delete().eq("item_id", item_id).execute()
    return {"message": f"アイテム({item_id})を削除しました"}


# ==========================================
# 🎒 一般ユーザー用：インベントリ管理 API（参照・売却・譲渡）
# ==========================================

@router.get("/inventory")
def get_user_inventory(current_user: Any = Depends(get_current_user_from_header)):
    supabase = get_supabase()
    user_id = current_user.id
    res = supabase.table("user_inventories") \
        .select("quantity, updated_at, items(item_id, name, description, base_price)") \
        .eq("user_id", user_id) \
        .gt("quantity", 0) \
        .execute()
    return res.data


@router.post("/sell-item")
def sell_item(req: SellItemRequest, current_user: Any = Depends(get_current_user_from_header)):
    supabase = get_supabase()
    user_id = current_user.id

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="個数は1以上を指定してください")

    inv_res = supabase.table("user_inventories") \
        .select("*, items(base_price, name)") \
        .eq("user_id", user_id) \
        .eq("item_id", req.item_id) \
        .execute()

    if not inv_res.data or inv_res.data[0]["quantity"] < req.quantity:
        raise HTTPException(status_code=400, detail="指定のアイテムを十分に所持していません")

    inventory_item = inv_res.data[0]
    unit_price = inventory_item["items"]["base_price"]
    total_earned = unit_price * req.quantity

    wallet_res = supabase.table("wallets") \
        .select("*") \
        .eq("wallet_id", req.wallet_id) \
        .eq("user_id", user_id) \
        .execute()

    if not wallet_res.data:
        raise HTTPException(status_code=404, detail="指定された受取口座が存在しないか所有権がありません")

    wallet = wallet_res.data[0]

    # インベントリ減算
    new_qty = inventory_item["quantity"] - req.quantity
    supabase.table("user_inventories") \
        .update({"quantity": new_qty}) \
        .eq("user_id", user_id) \
        .eq("item_id", req.item_id) \
        .execute()

    # 口座残高加算
    new_balance = wallet["balance"] + total_earned
    supabase.table("wallets") \
        .update({"balance": new_balance}) \
        .eq("id", wallet["id"]) \
        .execute()

    return {
        "message": f"「{inventory_item['items']['name']}」を{req.quantity}個売却し、{total_earned}G を受取口座に入金しました。"
    }


@router.post("/transfer-item")
def transfer_item(req: TransferItemRequest, current_user: Any = Depends(get_current_user_from_header)):
    supabase = get_supabase()
    sender_id = current_user.id

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="個数は1以上を指定してください")

    # 1. 差出人の所持チェック
    sender_inv = supabase.table("user_inventories") \
        .select("*, items(name)") \
        .eq("user_id", sender_id) \
        .eq("item_id", req.item_id) \
        .execute()

    if not sender_inv.data or sender_inv.data[0]["quantity"] < req.quantity:
        raise HTTPException(status_code=400, detail="指定のアイテムを十分に所持していません")

    # 2. 譲渡先ユーザーの検索
    target_id = None
    try:
        rpc_res = supabase.rpc("get_user_id_by_email", {"email_input": req.target_email}).execute()
        if rpc_res.data:
            target_id = rpc_res.data
    except Exception:
        pass

    if not target_id:
        prof_res = supabase.table("profiles").select("id").eq("email", req.target_email).execute()
        if prof_res.data:
            target_id = prof_res.data[0]["id"]

    if not target_id:
        raise HTTPException(status_code=404, detail="指定された受取人の国民が見つかりません")

    if sender_id == target_id:
        raise HTTPException(status_code=400, detail="自分自身にアイテムを譲渡することはできません")

    # 3. 差出人のインベントリ減算
    sender_item = sender_inv.data[0]
    supabase.table("user_inventories") \
        .update({"quantity": sender_item["quantity"] - req.quantity}) \
        .eq("user_id", sender_id) \
        .eq("item_id", req.item_id) \
        .execute()

    # 4. 譲渡先のインベントリ加算
    target_inv = supabase.table("user_inventories") \
        .select("*") \
        .eq("user_id", target_id) \
        .eq("item_id", req.item_id) \
        .execute()

    if target_inv.data:
        supabase.table("user_inventories") \
            .update({"quantity": target_inv.data[0]["quantity"] + req.quantity}) \
            .eq("user_id", target_id) \
            .eq("item_id", req.item_id) \
            .execute()
    else:
        supabase.table("user_inventories").insert({
            "user_id": target_id,
            "item_id": req.item_id,
            "quantity": req.quantity
        }).execute()

    return {
        "message": f"「{sender_item['items']['name']}」を {req.target_email} へ {req.quantity} 個譲渡しました。"
    }
