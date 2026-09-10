import random
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Dict, Any, Optional
from main import supabase, get_user_from_token  # main.pyから依存関係をインポート

router = APIRouter(prefix="/api/factory", tags=["factory"])

# ユーザーごとの工場進行セッション（メモリ保持）
factory_sessions: Dict[str, Dict[str, Any]] = {}

PROCESS_STEPS = [
    "① 材料の選定（正しい部品を選択）",
    "② 回路の配線（簡単な計算パズル）",
    "③ ギアの噛み合わせ（タイミング選択）",
    "④ 外装の溶接（連続タップ）",
    "⑤ 品質検査（最終チェック）"
]

class ProcessAction(BaseModel):
    step: int
    answer: Any
    wallet_id: Optional[str] = None

@router.get("/status")
def get_factory_status(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    # セッションが存在しない場合は初期生成
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
        raise HTTPException(status_code=400, detail="工程の同期がずれています。再読み込みしてください。")

    # 工程ごとの正解チェック
    if data.step == 1:
        if data.answer != session["target_part"]:
            raise HTTPException(status_code=400, detail="パーツが違います！")
    elif data.step == 2:
        if data.answer != session["math_answer"]:
            raise HTTPException(status_code=400, detail="配線エラー！計算が違います。")
    elif data.step == 3:
        if not (40 <= data.answer <= 60):  # タイミングメーター（40~60が成功ゾーン）
            raise HTTPException(status_code=400, detail="噛み合わせ失敗！タイミングが合っていません。")
    elif data.step == 4:
        if data.answer < 10:  # 10回連打が必要
            raise HTTPException(status_code=400, detail="溶接の圧力が足りません！")

    # 最終工程（第5工程：完成＆報酬付与）
    if data.step == 5:
        if not data.wallet_id:
            raise HTTPException(status_code=400, detail="受取口座が指定されていません。")

        reward_gold = random.randint(150, 250)
        
        # Supabaseのwalletsテーブルに残高反映
        w_res = supabase.table("wallets").select("*").eq("wallet_id", data.wallet_id).eq("user_id", user.id).execute()
        if not w_res.data:
            raise HTTPException(status_code=400, detail="指定口座が存在しないか権限がありません。")

        current_balance = w_res.data[0]["balance"]
        supabase.table("wallets").update({"balance": current_balance + reward_gold}).eq("id", w_res.data[0]["id"]).execute()

        # リセット
        factory_sessions[user.id] = generate_step_data(1)
        return {
            "completed": True,
            "reward": reward_gold,
            "message": f"製品完成！{reward_gold} Gold を獲得しました！"
        }

    # 次の工程へ進む
    next_step = data.step + 1
    factory_sessions[user.id] = generate_step_data(next_step)
    return {
        "completed": False,
        "next_step": factory_sessions[user.id]
    }

def generate_step_data(step: int) -> Dict[str, Any]:
    base = {"current_step": step, "title": PROCESS_STEPS[step - 1]}
    if step == 1:
        base.update({"target_part": random.choice(["ギアA", "ボルトB", "基板C"]), "options": ["ギアA", "ボルトB", "基板C"]})
    elif step == 2:
        a, b = random.randint(5, 20), random.randint(5, 20)
        base.update({"math_question": f"{a} + {b} = ?", "math_answer": a + b})
    elif step == 3:
        base.update({"instruction": "ゲージが緑色（40〜60）のタイミングで止めろ！"})
    elif step == 4:
        base.update({"instruction": "ボタンを10回連打して圧着しろ！"})
    elif step == 5:
        base.update({"instruction": "最終確認：完成ボタンを押して製品を出荷！"})
    return base
