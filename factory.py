import random
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional
from main import supabase, get_user_from_token

router = APIRouter(prefix="/api/factory", tags=["factory"])

factory_sessions: Dict[str, Dict[str, Any]] = {}

# プロセスをより機械的な「調整・組立」表現に変更
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

@router.get("/status")
def get_factory_status(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    if user.id not in factory_sessions:
        factory_sessions[user.id] = generate_step_data(1)

    return {
        "session": factory_sessions[user.id],
        "steps_total": 5
    }

@router.post("/process")
def process_step(data: ProcessAction, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    session = factory_sessions.get(user.id)

    if not session or session["current_step"] != data.step:
        raise HTTPException(status_code=400, detail="[ERROR: DESYNC] 工程シーケンスが一致しません。リセットしてください。")

    if data.step == 1:
        if data.answer != session["target_part"]:
            raise HTTPException(status_code=400, detail="[ERROR: MISMATCH] 不適合パーツがセットされました。")
    elif data.step == 2:
        if data.answer != session["math_answer"]:
            raise HTTPException(status_code=400, detail="[ERROR: CALIBRATION FAILED] 抵抗値の計算が不正確です。")
    elif data.step == 3:
        if not (45 <= data.answer <= 55):  # 許容公差を少し絞って精密感アップ
            raise HTTPException(status_code=400, detail="[ERROR: TOLERANCE EXCEEDED] トルク公差外です。結合失敗。")
    elif data.step == 4:
        if data.answer < 10:
            raise HTTPException(status_code=400, detail="[ERROR: PRESSURE LOW] 指定圧力（10 Bar）未達です。")

    if data.step == 5:
        if not data.wallet_id:
            raise HTTPException(status_code=400, detail="[ERROR: NO DESTINATION] 出荷先口座が未指定です。")

        # 報酬は15〜25の範囲
        reward_gold = random.randint(15, 25)
        
        w_res = supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data:
            raise HTTPException(status_code=400, detail="[ERROR: INVALID ACCOUNT] 指定口座が確認できません。")

        current_balance = w_res.data[0]["balance"]
        supabase.table("wallets").update({"balance": current_balance + reward_gold}).eq("id", w_res.data[0]["id"]).execute()

        factory_sessions[user.id] = generate_step_data(1)
        return {
            "completed": True,
            "reward": reward_gold,
            "message": f"[SYSTEM] 検品完了。シリアル#{random.randint(1000,9999)} 出荷済。+{reward_gold} Gold 獲得。"
        }

    next_step = data.step + 1
    factory_sessions[user.id] = generate_step_data(next_step)
    return {
        "completed": False,
        "next_step": factory_sessions[user.id]
    }

def generate_step_data(step: int) -> Dict[str, Any]:
    base = {"current_step": step, "title": PROCESS_STEPS[step - 1]}
    if step == 1:
        base.update({
            "target_part": random.choice(["SKF-6204ベアリング", "SUS304 M12ボルト", "IC-TTL7400回路"]),
            "options": ["SKF-6204ベアリング", "SUS304 M12ボルト", "IC-TTL7400回路"]
        })
    elif step == 2:
        voltage, current = random.randint(12, 48), random.randint(2, 6)
        base.update({
            "math_question": f"電圧 {voltage}V / 電流 {current}A の抵抗値 [Ω] を算出せよ",
            "math_answer": voltage // current  # 整数解になる設計
        })
    elif step == 3:
        base.update({"instruction": "クラッチ同期：公差範囲（45 - 55 Nm）でロックピンを噛み合わせよ"})
    elif step == 4:
        base.update({"instruction": "手動油圧ポンプ：規定圧（10 Bar）までストロークを実行せよ"})
    elif step == 5:
        base.update({"instruction": "全工程正常完了：最終シーケンスを実行して出荷先へ転送"})
    return base
