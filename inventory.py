from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
import random

# 既存の認証依存関数やSupabaseクライアントをインポートする想定です
# 環境のファイル構造に合わせてパスを微調整してください
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/api", tags=["inventory"])

# --- リクエストモデルの定義 ---
class ItemCreateUpdate(BaseModel):
    item_id: str
    name: str
    description: Optional[str] = ""
    base_price: int

class SellItemRequest(BaseModel):
    item_id: str
    quantity: int
    wallet_id: str


# --- 国王判定ヘルパー ---
async def verify_king(user: dict = Depends(get_current_user)):
    # ユーザー情報から国王権限を検証
    if not user.get("is_king") and user.get("role") != "king":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="国王専用の操作です"
        )
    return user


# ==========================================
# 👑 国王専用：アイテムマスター管理 API
# ==========================================

@router.get("/admin/items")
async def get_admin_items(current_user: dict = Depends(verify_king)):
    """アイテム一覧の取得（管理者用）"""
    res = supabase.table("items").select("*").order("created_at").execute()
    return res.data

@router.post("/admin/items")
async def upsert_admin_item(item: ItemCreateUpdate, current_user: dict = Depends(verify_king)):
    """アイテムの新規登録・更新（新規追加または価格変更など）"""
    data = {
        "item_id": item.item_id,
        "name": item.name,
        "description": item.description,
        "base_price": item.base_price
    }
    res = supabase.table("items").upsert(data).execute()
    return {"message": "アイテム情報を更新しました", "data": res.data}

@router.delete("/admin/items/{item_id}")
async def delete_admin_item(item_id: str, current_user: dict = Depends(verify_king)):
    """アイテムの削除"""
    supabase.table("items").delete().eq("item_id", item_id).execute()
    return {"message": f"アイテム({item_id})を削除しました"}


# ==========================================
# 🎒 一般ユーザー用：インベントリ・採掘・売却 API
# ==========================================

@router.get("/inventory")
async def get_user_inventory(current_user: dict = Depends(get_current_user)):
    """自分の所持アイテム一覧を取得（アイテム詳細情報と結合）"""
    user_id = current_user["id"]
    # user_inventories と items をリレーション取得
    res = supabase.table("user_inventories") \
        .select("quantity, updated_at, items(item_id, name, description, base_price)") \
        .eq("user_id", user_id) \
        .gt("quantity", 0) \
        .execute()
    return res.data


@router.post("/mine")
async def mine_work(current_user: dict = Depends(get_current_user)):
    """労働（採掘）：ランダムでアイテムを獲得"""
    user_id = current_user["id"]

    # 1. DBから登録済みアイテムを取得
    items_res = supabase.table("items").select("*").execute()
    if not items_res.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="王国に採掘可能なアイテムが存在しません"
        )

    # 2. ランダムで1つ抽選（全アイテムから均等または重み付け）
    obtained_item = random.choice(items_res.data)
    item_id = obtained_item["item_id"]

    # 3. ユーザーの既存インベントリを確認
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
async def sell_item(req: SellItemRequest, current_user: dict = Depends(get_current_user)):
    """アイテムを売却して指定の口座へゴールドを入金"""
    user_id = current_user["id"]

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="個数は1以上を指定してください")

    # 1. 所持チェック
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

    # 2. 口座所有権の確認
    wallet_res = supabase.table("wallets") \
        .select("*") \
        .eq("wallet_id", req.wallet_id) \
        .eq("user_id", user_id) \
        .execute()

    if not wallet_res.data:
        raise HTTPException(status_code=404, detail="指定された受取口座が存在しないか所有権がありません")

    wallet = wallet_res.data[0]

    # 3. インベントリの減算
    new_qty = inventory_item["quantity"] - req.quantity
    supabase.table("user_inventories") \
        .update({"quantit
