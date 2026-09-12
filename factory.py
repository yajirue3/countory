import random
import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional

from db import get_supabase

router = APIRouter(prefix="/api/factory", tags=["factory"])

factory_sessions: Dict[str, Dict[str, Any]] = {}
user_wear: Dict[str, int] = {}

PROCESS_STEPS = [
    "① コンポーネント選定（規格部品の受入）",
    "② 回路抵抗値のキャリブレーション（4本帯）",
    "③ クラッチ・トルクの同期（回転角調整）",
    "④ 圧着シリンダーの油圧加圧",
    "⑤ 最終精度検査および出荷シリアル発行"
]

class ProcessAction(BaseModel):
    step: int
    answer: Any
    wallet_id: Optional[str] = None

async def get_user_from_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    token = authorization.split(" ")[1]
    try:
        client = await get_supabase()
        user_res = await client.auth.get_user(token)
        return user_res.user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"トークン検証エラー: {str(e)}")

def generate_step_data(step: int) -> Dict[str, Any]:
    base = {"current_step": step, "title": PROCESS_STEPS[step - 1]}
    if step == 1:
        parts = ["SKF-6204ベアリング", "SUS304 M12ボルト", "IC-TTL7400回路", "高耐圧シリコンパッキン"]
        base.update({"target_part": random.choice(parts), "options": random.sample(parts, len(parts))})
    elif step == 2:
        d1 = random.randint(1, 9)
        d2 = random.randint(0, 9)
        mult = random.randint(0, 4)
        tol_val = random.choice([10, 11])
        target_ohm = (d1 * 10 + d2) * (10 ** mult)
        base.update({
            "math_question": f"目標抵抗値: {target_ohm} Ω (公差 ±{5 if tol_val==10 else 10}%) を設定せよ",
            "color_ans": [d1, d2, mult, tol_val]
        })
    elif step == 3:
        base.update({"instruction": "クラッチ同期：規定トルク範囲（45 - 55 Nm）内でロックピンを結合せよ"})
    elif step == 4:
        base.update({"instruction": "手動油圧シリンダー：規定圧（10 Bar）に到達するまでポンピングを実行せよ"})
    elif step == 5:
        base.update({"instruction": "全機械シーケンス正常完了：最終品質検査をパスして出荷転送を実行"})
    return base

def mask_session_data(session: Dict[str, Any]) -> Dict[str, Any]:
    return {k: session[k] for k in ["current_step", "title", "options", "math_question", "instruction", "serial_number", "target_part"] if k in session}

@router.get("/status")
async def get_factory_status(authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    if user.id not in factory_sessions:
        factory_sessions[user.id] = generate_step_data(1)
        factory_sessions[user.id]["serial_number"] = f"MRK-SYS-{int(time.time())%100000}-{random.randint(100,999)}"
        user_wear[user.id] = 0
    return {
        "session": mask_session_data(factory_sessions[user.id]),
        "steps_total": len(PROCESS_STEPS),
        "system_status": "ONLINE",
        "wear": user_wear.get(user.id, 0)
    }

@router.post("/maintain")
async def maintain_system(authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    user_wear[user.id] = 0
    return {"message": "[SYSTEM] エアパージ・給油完了。稼働を再開します。", "wear": 0}

@router.post("/process")
async def process_step(data: ProcessAction, authorization: str = Header(None)):
    user = await get_user_from_token(authorization)
    session = factory_sessions.get(user.id)
    current_wear = user_wear.get(user.id, 0)

    if current_wear >= 100:
        raise HTTPException(status_code=400, detail="[ERROR: WEAR LIMIT] 設備が摩耗限界です。手動パージを実行してください。")
    if not session or session["current_step"] != data.step:
        raise HTTPException(status_code=400, detail="[ERROR: DESYNC] 工程が不整合です。ラインを再読み込みします。")

    user_wear[user.id] = min(100, current_wear + random.randint(5, 12))

    if data.step == 1 and data.answer != session["target_part"]:
        raise HTTPException(status_code=400, detail="[ERROR: MISMATCH] 規格外の不適合パーツです。")
    elif data.step == 2:
        try:
            ans_list = [int(x) for x in data.answer]
            if len(ans_list) != 4 or ans_list != session["color_ans"]: raise ValueError
        except:
            raise HTTPException(status_code=400, detail="[ERROR: CALIBRATION FAILED] 抵抗値または公差が目標と一致しません。")
    elif data.step == 3:
        try: val = int(data.answer)
        except: val = 0
        if not (45 <= val <= 55): raise HTTPException(status_code=400, detail=f"[ERROR: TOLERANCE EXCEEDED] トルク公差外（{val} Nm）。")
    elif data.step == 4:
        try: val = int(data.answer)
        except: val = 0
        if val < 10: raise HTTPException(status_code=400, detail=f"[ERROR: PRESSURE LOW] 油圧不足（{val} Bar）。")
    elif data.step == 5:
        if not data.wallet_id: raise HTTPException(status_code=400, detail="[ERROR: NO DESTINATION] 報酬転送用口座がありません。")
        reward_gold = random.randint(15, 25)
        supabase = await get_supabase()
        w_res = await supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data: raise HTTPException(status_code=400, detail="[ERROR: INVALID ACCOUNT] 口座が存在しません。")
        await supabase.table("wallets").update({"balance": int(w_res.data[0]["balance"]) + reward_gold}).eq("id", w_res.data[0]["id"]).execute()
        
        serial = session.get("serial_number", "UNKNOWN")
        factory_sessions[user.id] = generate_step_data(1)
        factory_sessions[user.id]["serial_number"] = f"MRK-SYS-{int(time.time())%100000}-{random.randint(100,999)}"
        return {
            "completed": True, "reward": reward_gold, "serial": serial, "wear": user_wear[user.id],
            "message": f"製品出荷完了。SERIAL: {serial} | ＋{reward_gold}G 獲得",
            "next_step": mask_session_data(factory_sessions[user.id])
        }

    factory_sessions[user.id] = generate_step_data(data.step + 1)
    factory_sessions[user.id]["serial_number"] = session.get("serial_number")
    return {"completed": False, "wear": user_wear[user.id], "next_step": mask_session_data(factory_sessions[user.id])}
