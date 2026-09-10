import asyncio
import copy
import json
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import (
    APIRouter, HTTPException, Header, Request, WebSocket, 
    WebSocketDisconnect, status
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from supabase import create_client, Client

# --- ログ設定 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ContractDuel")

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def get_user_from_token(token: str) -> Any:
    """Supabaseトークンを検証してユーザー情報を取得"""
    if not supabase:
        # 開発用フォールバック
        return type("User", (), {"id": f"dummy_{token[:8]}"})()
    try:
        user_res = supabase.auth.get_user(token)
        if not user_res or not user_res.user:
            raise HTTPException(status_code=401, detail="無効なトークンです")
        return user_res.user
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="認証に失敗しました")


# ==========================================
# 1. 完全版カードマスターデータ & 効果エンジン
# ==========================================
CARD_MASTER: List[Dict[str, Any]] = [
    # ユニットカード
    {"id": "u01", "name": "突撃兵", "type": "unit", "cost": 1, "atk": 2, "hp": 1, "desc": "召喚酔いなし（即時攻撃可能）", "haste": True},
    {"id": "u02", "name": "重装騎士", "type": "unit", "cost": 3, "atk": 2, "hp": 5, "desc": "挑発（相手は先にこのユニットを攻撃しなければならない）", "taunt": True},
    {"id": "u03", "name": "魔導士", "type": "unit", "cost": 2, "atk": 3, "hp": 2, "desc": "標準的なアタッカー"},
    {"id": "u04", "name": "ドラゴン", "type": "unit", "cost": 6, "atk": 7, "hp": 6, "desc": "圧倒的な打点を持つ高コストユニット"},
    {"id": "u05", "name": "吸血鬼", "type": "unit", "cost": 4, "atk": 3, "hp": 4, "desc": "ドレイン（ダメージを与えた分プレイヤーのHP回復）", "lifesteal": True},
    
    # 呪文カード
    {"id": "s01", "name": "火炎球", "type": "spell", "cost": 2, "effect": "deal_damage", "val": 3, "target": "any", "desc": "敵かユニット1体に3ダメージ"},
    {"id": "s02", "name": "全体閃光", "type": "spell", "cost": 4, "effect": "aoe_damage", "val": 2, "desc": "敵の全ユニットに2ダメージ"},
    {"id": "s03", "name": "神聖なる恵み", "type": "spell", "cost": 2, "effect": "heal_leader", "val": 5, "desc": "自分のヒーローHPを5回復"},
    {"id": "s04", "name": "戦術的ドロー", "type": "spell", "cost": 3, "effect": "draw_cards", "val": 2, "desc": "カードを2枚引く"},
    {"id": "s05", "name": "強制接収", "type": "spell", "cost": 5, "effect": "destroy_target", "target": "unit", "desc": "敵ユニット1体を即死させる"}
]

# ==========================================
# 2. データ構造とメモリ状態管理
# ==========================================
class CreateRoomRequest(BaseModel):
    wallet_id: str
    bet_amount: int = Field(..., gt=0)

class GameRoom:
    def __init__(self, room_id: str, host_id: str, host_name: str, host_wallet: str, bet_amount: int):
        self.room_id = room_id
        self.host_id = host_id
        self.host_name = host_name
        self.host_wallet = host_wallet
        self.guest_id: Optional[str] = None
        self.guest_name: Optional[str] = None
        self.guest_wallet: Optional[str] = None
        self.bet_amount = bet_amount
        
        self.status = "WAITING"  # WAITING, DRAFTING, PLAYING, FINISHED
        self.lock = asyncio.Lock()  # 非同期スレッドセーフのためのロック
        self.timer_task: Optional[asyncio.Task] = None
        self.turn_time_left = 30
        
        # ゲームステート詳細
        self.turn_user_id: Optional[str] = None
        self.turn_count = 1
        self.draft_pool: List[dict] = []
        self.draft_options: Dict[str, List[dict]] = {}
        self.decks: Dict[str, List[dict]] = {}
        self.hands: Dict[str, List[dict]] = {}
        self.boards: Dict[str, List[dict]] = {}  # [{instance_id, id, name, atk, max_hp, current_hp, can_attack, taunt, lifesteal}]
        self.hp: Dict[str, int] = {}
        self.mp: Dict[str, int] = {}
        self.max_mp: Dict[str, int] = {}
        self.winner_id: Optional[str] = None

ROOMS: Dict[str, GameRoom] = {}
CONNECTIONS: Dict[str, Dict[str, WebSocket]] = {}


# ==========================================
# 3. HTTP REST API
# ==========================================
@router.get("/card", response_class=HTMLResponse)
def get_card_page(request: Request):
    return templates.TemplateResponse(request=request, name="card.html")

@router.get("/api/card/rooms")
def list_rooms():
    active_rooms = []
    for r_id, r in ROOMS.items():
        if r.status == "WAITING":
            active_rooms.append({
                "room_id": r_id,
                "host_name": r.host_name,
                "bet_amount": r.bet_amount
            })
    return {"rooms": active_rooms}

@rout
