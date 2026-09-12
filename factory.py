import random
import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from db import get_supabase

router = APIRouter(prefix="/api/factory", tags=["factory"])

# -------------------------------------------------------------------
# メモリ保持データ
# -------------------------------------------------------------------
factory_sessions: Dict[str, Dict[str, Any]] = {}
user_wear: Dict[str, int] = {}  # 設備摩耗度のトラッキング (0-100%)

factory_metrics: Dict[str, int] = {
    "total_units_produced": 0,
    "total_calibration_errors": 0,
    "system_up_time_sec": int(time.time())
}

PROCESS_STEPS = [
    "① コンポーネント選定（規格部品の受入）",
    "② 回路抵抗値のキャリブレーション（カラーコード選定）",
    "③ クラッチ・トルクの同期（回転角調整）",
    "④ 圧着シリンダーの油圧加圧",
    "⑤ 最終精度検査および出荷シリアル発行"
]

# -------------------------------------------------------------------
# リクエスト / レスポンス モデル
# -------------------------------------------------------------------
class ProcessAction(BaseModel):
    step: int
    answer: Any
    wallet_id: Optional[str] = None

class SystemDiagnostics(BaseModel):
    status: str
    uptime_seconds: int
    total_units_produced: int
    error_count: int

# -------------------------------------------------------------------
# 補助関数
# -------------------------------------------------------------------
async def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        client = await get_supabase()
        user_res = await client.auth.get_user(token)
        return user_res.user
    except Exception:
        raise HTTPException(status_code=401, detail="無効なトークンです")

def generate_serial_number() -> str:
    prefix = "MRK-SYS"
    timestamp = int(time.time()) % 100000
    rand_id = random.randint(100, 999)
    return f"{prefix}-{timestamp}-{rand_id}"

def log_system_event(level: str, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}] {message}")

def generate_step_data(step: int) -> Dict[str, Any]:
    base = {
        "current_step": step, 
        "title": PROCESS_STEPS[step - 1]
    }
    
    if step == 1:
        parts = ["SKF-6204ベアリング", "SUS304 M12ボルト", "IC-TTL7400回路", "高耐圧シリコンパッキン"]
        target = random.choice(parts)
        base.update({
            "target_part": target,
            "options": random.sample(parts, len(parts))
        })

    elif step == 2:
        # カラーコードロジック (1桁目, 2桁目, 乗数)
        d1 = random.randint(1, 9)
        d2 = random.randint(0, 9)
        mult = random.randint(0, 4)
        target_ohm = (d1 * 10 + d2) * (10 ** mult)
        
        base.update({
            "math_question": f"目標抵抗値: {target_ohm} Ω をカラーコードで設定せよ",
            "color_ans": [d1, d2, mult]
        })

    elif step == 3:
        base.update({
            "instruction": "クラッチ同期：規定トルク範囲（45 - 55 Nm）内でロックピンを結合せよ"
        })

    elif step == 4:
        base.update({
            "instruction": "手動油圧シリンダー：規定圧（10 Bar）に到達するまでポンピングを実行せよ"
        })

    elif step == 5:
        base.update({
            "instruction": "全機械シーケンス正常完了：最終品質検査をパスして出荷転送を実行"
        })

    return base

def reset_session(user_id: str) -> Dict[str, Any]:
    factory_sessions[user_id] = generate_step_data(1)
    factory_sessions[user_id]["serial_number"] = generate_serial_number()
    return factory_sessions[user_id]

# -------------------------------------------------------------------
# エンドポイント
# -------------------------------------------------------------------
@router.get("/status")
async def get_factory_status(authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    
    if user.id not in factory_sessions:
        log_system_event("info", f"New assembly session initialized for User: {user.id}")
        reset_session(user.id)
        user_wear[user.id] = 0

    return {
        "session": factory_sessions[user.id],
        "steps_total": len(PROCESS_STEPS),
        "system_status": "ONLINE",
        "wear": user_wear.get(user.id, 0)
    }

@router.post("/maintain")
async def maintain_system(authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_wear[user.id] = 0
    log_system_event("info", f"Maintenance performed by User: {user.id}")
    return {"message": "[SYSTEM] エアパージ・給油完了。稼働を再開します。", "wear": 0}

@router.post("/process")
async def process_step(data: ProcessAction, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    session = factory_sessions.get(user.id)
    current_wear = user_wear.get(user.id, 0)

    if current_wear >= 100:
        raise HTTPException(
            status_code=400, 
            detail="[ERROR: TOOL WEAR LIMIT] 設備が摩耗限界です。メンテナンスを実行してください。"
        )

    if not session or session["current_step"] != data.step:
        log_system_event("warn", f"Desync detected for User: {user.id} at Step: {data.step}")
        raise HTTPException(
            status_code=400, 
            detail="[ERROR: DESYNC] 工程シーケンスが不整合です。ラインを再読み込みしてください。"
        )

    # 摩耗の進行 (5%〜12%)
    user_wear[user.id] = min(100, current_wear + random.randint(5, 12))

    # ステップ 1 バリデーション
    if data.step == 1:
        if data.answer != session["target_part"]:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Part mismatch by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: MISMATCH] 不適合パーツ（{data.answer}）が挿入されました。要求: {session['target_part']}"
            )

    # ステップ 2 バリデーション (カラーコード)
    elif data.step == 2:
        try:
            ans_list = [int(x) for x in data.answer]
            if len(ans_list) != 3: raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="[ERROR: INVALID INPUT] カラーコード配列が不正です。")

        if ans_list != session["color_ans"]:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Color code error by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: CALIBRATION FAILED] 抵抗値が不一致です。入力値: {ans_list}"
            )

    # ステップ 3 バリデーション
    elif data.step == 3:
        try:
            val = int(data.answer)
        except (ValueError, TypeError):
            val = 0

        if not (45 <= val <= 55):
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Torque limit out of range by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: TOLERANCE EXCEEDED] トルク公差外（{val} Nm）。規定値: 50±5 Nm"
            )

    # ステップ 4 バリデーション
    elif data.step == 4:
        try:
            val = int(data.answer)
        except (ValueError, TypeError):
            val = 0

        if val < 10:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Pressure low by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: PRESSURE LOW] 油圧不足（{val} Bar）。規定圧 10 Bar 未満です。"
            )

    # ステップ 5 出荷 & 報酬処理
    if data.step == 5:
        if not data.wallet_id:
            raise HTTPException(
                status_code=400, 
                detail="[ERROR: NO DESTINATION] 報酬転送用口座（wallet_id）が指定されていません。"
            )

        reward_gold = random.randint(15, 25)
        
        supabase = await get_supabase()
        w_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data:
            raise HTTPException(
                status_code=400, 
                detail="[ERROR: INVALID ACCOUNT] 指定された口座が存在しないかアクセス権がありません。"
            )

        current_balance = int(w_res.data[0]["balance"])
        await supabase.table("wallets").update({"balance": current_balance + reward_gold}).eq("id", w_res.data[0]["id"]).execute()

        factory_metrics["total_units_produced"] += 1
        completed_serial = session.get("serial_number", "UNKNOWN")
        log_system_event("info", f"Unit completed. Serial: {completed_serial}, Reward: {reward_gold} G")

        next_session = reset_session(user.id)
        
        return {
            "completed": True,
            "reward": reward_gold,
            "serial": completed_serial,
            "wear": user_wear[user.id],
            "message": f"[SYSTEM] 製品出荷完了。SERIAL: {completed_serial} | ＋{reward_gold} Gold 獲得。",
            "next_step": next_session
        }

    # 次のステップへ進行
    next_step = data.step + 1
    session_data = generate_step_data(next_step)
    session_data["serial_number"] = session.get("serial_number")
    factory_sessions[user.id] = session_data

    return {
        "completed": False,
        "wear": user_wear[user.id],
        "next_step": factory_sessions[user.id]
    }
