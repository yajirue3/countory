import random
import time
import main
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional

router = APIRouter(prefix="/api/factory", tags=["factory"])

# -------------------------------------------------------------------
# メモリ保持データ
# -------------------------------------------------------------------
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
        # 必ず整数で割り切れる数値を生成（無限小数を排除）
        current = random.choice([2, 3, 4, 6])
        multiplier = random.randint(2, 10)
        voltage = current * multiplier
        
        base.update({
            "math_question": f"回路電圧 {voltage}V / 規定電流 {current}A の適正抵抗値 [Ω] を設定せよ",
            "math_answer": multiplier
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
    user = await main.get_user_from_token(authorization)
    
    if user.id not in factory_sessions:
        log_system_event("info", f"New assembly session initialized for User: {user.id}")
        reset_session(user.id)

    return {
        "session": factory_sessions[user.id],
        "steps_total": len(PROCESS_STEPS),
        "system_status": "ONLINE"
    }

@router.get("/diagnostics")
async def get_diagnostics():
    uptime = int(time.time()) - factory_metrics["system_up_time_sec"]
    return SystemDiagnostics(
        status="OPERATIONAL",
        uptime_seconds=uptime,
        total_units_produced=factory_metrics["total_units_produced"],
        error_count=factory_metrics["total_calibration_errors"]
    )

@router.post("/process")
async def process_step(data: ProcessAction, authorization: str = Header(None)):
    user = await main.get_user_from_token(authorization)
    session = factory_sessions.get(user.id)

    if not session or session["current_step"] != data.step:
        log_system_event("warn", f"Desync detected for User: {user.id} at Step: {data.step}")
        raise HTTPException(
            status_code=400, 
            detail="[ERROR: DESYNC] 工程シーケンスが不整合です。ラインを再読み込みしてください。"
        )

    # ステップ 1 バリデーション
    if data.step == 1:
        if data.answer != session["target_part"]:
            factory_metrics["total_calibration_errors"] += 1
            log_system_event("error", f"Part mismatch by User: {user.id}")
            raise HTTPException(
                status_code=400, 
                detail=f"[ERROR: MISMATCH] 不適合パーツ（{data.answer}）が挿入されました。要求: {session['target_part']}"
            )

    # ステップ 2 バリデーション
    elif data.step == 2:
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
        
        supabase = await main.get_supabase()
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
        "next_step": factory_sessions[user.id]
    }
