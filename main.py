# --------------------------------------------------
# 自由市場 (エスクロー契約) API
# --------------------------------------------------

# 1. 契約一覧（OPENな未受注契約のみ取得 -> 受注されたら一覧から自動非表示化）
@app.get("/api/contracts")
def get_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    # 既存のパスを維持しつつ、未受注(OPEN)の契約のみを返す
    res = supabase.table("contracts").select("*").eq("status", "OPEN").execute()
    return {
        "contracts": res.data,
        "current_user_id": user.id,
        "is_king": is_king(user.id)
    }

# 自分の関わっている契約一覧を取得（進行中・マイ契約表示用：新規追加）
@app.get("/api/my-contracts")
def get_my_contracts(authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    # ユーザー所有のウォレットを取得
    wallets_res = supabase.table("wallets").select("wallet_id").eq("user_id", user.id).execute()
    wallet_ids = [w["wallet_id"] for w in wallets_res.data]
    
    if not wallet_ids:
        return []

    # 自分が作成者か受注者である契約を取得
    res = supabase.table("contracts").select("*").or_(
        f"creator_wallet_id.in.({','.join(wallet_ids)}),acceptor_wallet_id.in.({','.join(wallet_ids)})"
    ).execute()
    return res.data

# 2. 契約書の掲示（作成時の残高チェック＆事前引き落とし追加）
@app.post("/api/contracts")
def create_contract(req: ContractCreate, authorization: str = Header(None)):
    user = get_user_from_token(authorization)
    
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="金額は1以上である必要があります")

    # 指定ウォレットの所有権と残高チェック【不具合2解消】
    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.creator_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=403, detail="無効なウォレットです")
    
    wallet = w_res.data[0]
    if wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="残高が不足しているため契約書を掲示できません")

    # 先に資金を引き落としてエスクロー預かり状態にする
    new_balance = wallet["balance"] - req.amount
    supabase.table("wallets").update({"balance": new_balance}).eq("wallet_id", req.creator_wallet_id).execute()

    # 契約の登録
    contract_data = {
        "title": req.title,
        "description": req.description,
        "amount": req.amount,
        "creator_wallet_id": req.creator_wallet_id,
        "status": "OPEN"
    }
    res = supabase.table("contracts").insert(contract_data).execute()
    return {"message": "契約書を市場に掲示しました", "contract": res.data[0]}

# 3. 契約の受注（排他制御の強化）
@app.post("/api/contracts/{contract_id}/accept")
def accept_contract(contract_id: str, req: ContractAccept, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # 受注用ウォレットの所有権チェック
    w_res = supabase.table("wallets").select("*").eq("wallet_id", req.acceptor_wallet_id).eq("user_id", user.id).execute()
    if not w_res.data:
        raise HTTPException(status_code=403, detail="無効なウォレットです")

    # 対象契約のステータスチェック【不具合1解消：二重受注の防止】
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が存在しません")
    
    contract = c_res.data[0]
    if contract["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="この契約は既に他のユーザーに受注されたか、終了しています")

    if contract["creator_wallet_id"] == req.acceptor_wallet_id:
        raise HTTPException(status_code=400, detail="自分の作成した契約を受注することはできません")

    # ステータスを IN_PROGRESS に更新し、受注ウォレットを記録
    update_res = supabase.table("contracts").update({
        "status": "IN_PROGRESS",
        "acceptor_wallet_id": req.acceptor_wallet_id
    }).eq("id", contract_id).execute()

    return {"message": "契約を受注しました", "contract": update_res.data[0]}

# 4. 依頼完了処理（新規追加）【不具合3解消】
@app.post("/api/contracts/{contract_id}/complete")
def complete_contract(contract_id: str, authorization: str = Header(None)):
    user = get_user_from_token(authorization)

    # 契約の取得
    c_res = supabase.table("contracts").select("*").eq("id", contract_id).execute()
    if not c_res.data:
        raise HTTPException(status_code=404, detail="契約が存在しません")
    
    contract = c_res.data[0]
    if contract["status"] != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail="進行中の契約のみ完了できます")

    # 発注者のウォレット所有権チェック
    creator_w = supabase.table("wallets").select("*").eq("wallet_id", contract["creator_wallet_id"]).eq("user_id", user.id).execute()
    if not creator_w.data:
        raise HTTPException(status_code=403, detail="この契約を完了させる権限がありません")

    acceptor_wallet_id = contract["acceptor_wallet_id"]
    reward_amount = contract["amount"]

    # 受注者のウォレット残高を加算（エスクローからの送金）
    acceptor_w = supabase.table("wallets").select("balance").eq("wallet_id", acceptor_wallet_id).execute()
    if not acceptor_w.data:
        raise HTTPException(status_code=400, detail="受注者のウォレットが見つかりません")

    new_acceptor_balance = acceptor_w.data[0]["balance"] + reward_amount
    supabase.table("wallets").update({"balance": new_acceptor_balance}).eq("wallet_id", acceptor_wallet_id).execute()

    # ステータスを COMPLETED に変更
    supabase.table("contracts").update({"status": "COMPLETED"}).eq("id", contract_id).execute()

    return {"message": "依頼が完了し、報酬が受任者に支払われました"}
