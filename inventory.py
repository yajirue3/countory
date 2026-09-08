import random
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel

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


# --- 循環参照を回避するための依存取得ヘルパー ---
def get_supabase():
    # 関数呼び出し時に main から取得することで循環参照を防止
    from main import supabase
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabaseが設定されていません")
    return supabase

def get_current_user_from_header(authorization: str = Header(None)):
    from main import get_user_from_token
    return get_user_from_token(authorization)

def verify_king_user(authorization: str = Header(None)):
    from main import get_user_from_token, is_king
    user = get_user_from_token(authorization)
    if not is_king(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="国王専用の操作です"
        )
    return user


# ==========================================
# 👑 国王専用：アイテムマスター管理 API
# ==========================================

@router.get("/admin/items")
def get_admin_items(current_user=Depends(verify_king_user)):
    supabase = get_supabase()
    res = supabase.table("items").select("*").order("created_at").execute()
    return res.data

@router.post("/admin/items")
def upsert_admin_item(item: ItemCreateUpdate, current_user=Depends(verify_king_user)):
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
def delete_admin_item(item_id: str, current_user=Depends(verify_king_user)):
    supabase = get_supabase()
    supabase.table("items").delete().eq("item_id", item_id).execute()
    return {"message": f"アイテム({item_id})を削除しました"}


# ==========================================
# 🎒 一般ユーザー用：インベントリ・採掘・売却・譲渡 API
# ==========================================

@router.get("/inventory")
def get_user_inventory(current_user=Depends(get_current_user_from_header)):
    supabase = get_supabase()
    user_id = current_user.id
    res = supabase.table("user_inventories") \
        .select("quantity, updated_at, items(item_id, name, description, base_price)") \
        .eq("user_id", user_id) \
        .gt("quantity", 0) \
        .execute()
    return res.data


@router.post("/mine")
def mine_work(current_user=Depends(get_current_user_from_header)):
    supabase = get_supabase()
    user_id = current_user.id

    items_res = supabase.table("items").select("*").execute()
    if not items_res.data:
        raise HTTPException(status_code=400, detail="王国に採掘可能なアイテムが存在しません")

    obtained_item = random.choice(items_res.data)
    item_id = obtained_item["item_id"]

    inv_res = supabase.table("user_inventories") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("item_id", item_id) \
        .execute()

    if inv_res.data:
        current_qty = inv_res.data[0]["quantity"]
        supabase.table("user_inventories") \
            .update({"quantity": current_qty + 1}) \
            .eq("user_id", user_id) \
            .eq("item_id", item_id) \
            .execute()
    else:
        supabase.table("user_inventories").insert({
            "user_id": user_id,
            "item_id": item_id,
            "quantity": 1
        }).execute()

    return {
        "message": f"採掘に成功！「{obtained_item['name']}」を1個獲得しました。",
        "item": obtained_item
    }


@router.post("/sell-item")
def sell_item(req: SellItemRequest, current_user=Depends(get_current_user_from_header)):
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
def transfer_item(req: TransferItemRequest, current_user=Depends(get_current_user_from_header)):
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
