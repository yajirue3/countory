import random
import time
import main
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional

router = APIRouter(prefix="/api/factory", tags=["factory"])

factory_sessions: Dict[str, Dict[str, Any]] = {}

factory_metrics: Dict[str, int] = {
    "total_units_produced": 0,
    "total_calibration_errors": 0,
    "system_up_time_sec": int(time.time())
}

PROCESS_STEPS = [
    "① コンポーネント選定（規格部品の受入）",
    "② 回路抵抗値のキャリブレーション（オームの法則）",
    "③ クラッチ・トルクの同期（回転角調整）",
    "④ 圧着シリンダーの油圧加圧",
    "⑤ 最終精度検査および出荷シリアル発行"
]

class ProcessAction(BaseModel):
    step: int
    answer: Any
    wallet_id: Optional[str] = None

class SystemDiagnostics(BaseModel):
    status: str
    uptime_seconds: int
    total_units_produced: int
    error_count: int

def generate_serial_number() -> str:
    prefix = "MRK-SYS"
    timestamp = int(time.time()) % 100000
    rand_id = random.randint(100, 999)
    return f"{prefix}-{timestamp}-{rand_id}"

def log_system_event(level: str, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}] {message}")

def reset_session(user_id: str) -> Dict[str, Any]:
    factory_sessions[user_id] = generate_step_data(1)
    factory_sessions[user_id]["serial_number"] = generate_serial_number()
    return factory_sessions[user_id]

@router.get("/status")
def get_factory_status(authorization: str = Header(None)):
    user = main.get_user_from_token(authorization)
    
    if user.id not in factory_sessions:
        log_system_event("info", f"New assembly session initialized for User: {user.id}")
        reset_session(user.id)

    return {
        "session": factory_sessions[user.id],
        "steps_total": len(PROCESS_STEPS),
        "system_status": "ONLINE"
    }

@router.get("/diagnostics")
def get_diagnostics():
    uptime = int(time.time()) - factory_metrics["system_up_time_sec"]
    return SystemDiagnostics(
        status="OPERATIONAL",
        uptime_seconds=uptime,
        total_units_produced=factory_metrics["total_units_produced"],
        error_count=factory_metrics["total_calibration_errors"]
    )

@router.post("/process")
def process_step(data: ProcessAction, authorization: str = Header(None)):
    user = main.get_user_from_token(authorization)
    session = factory_sessions.get(user.id)

    if not session or session["current_step"] != data.step:
        log_system_event("warn", f"Desync detected for User: {user.id} at Step: {data.step}")
        raise HTTPException(
            status_code=400, 
            detail="[ERROR: DESYNC] 工程シーケンスが不整合です。ラインを再読み込みしてください。"
        )

    if data.step == 1:
        if data.answer != session["target_part"]:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Part mismatch by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: MISMATCH] 不適合パーツ（{data.answer}）が挿入されました。要求: {session['target_part']}"
            )

    elif data.step == 2:
        # 整数値として正解を比較
        try:
            user_ans = int(data.answer)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="[ERROR: INVALID INPUT] 整数を入力してください。")

        if user_ans != session["math_answer"]:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Calibration error by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: CALIBRATION FAILED] 抵抗値演算エラー。算出値: {user_ans} Ω"
            )

    elif data.step == 3:
        # トルクメーターの範囲チェック（整数値）
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

    elif data.step == 4:
        try:
            val = int(data.answer)
        except (ValueError, TypeError):
            val = 0

        if val < 10:
            factory_metrics["total_calibration_errors"] += 1
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: PRESSURE LOW] 油圧不足（{val} Bar）。規定圧 10 Bar 未満です。"
            )

    if data.step == 5:
        if not data.wallet_id:
            raise HTTPException(
                status_code=400, 
                detail="[ERROR: NO DESTINATION] 報酬転送用口座（wallet_id）が指定されていません。"
            )

        reward_gold = random.randint(15, 25)
        
        w_res = main.supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data:
            raise HTTPException(
                sta
