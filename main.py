import os
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from passlib.context import CryptContext
from jose import JWTError, jwt

# ==========================================
# 1. データベース & 基本設定
# ==========================================
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

SECRET_KEY = os.getenv("SECRET_KEY", "SUPER_SECRET_KEY_CHANGE_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app = FastAPI(title="Marketplace API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. ORM モデル定義
# ==========================================
class UserDB(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: secrets.token_hex(8))
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    wallets = relationship("WalletDB", back_populates="owner")


class WalletDB(Base):
    __tablename__ = "wallets"

    id = Column(String, primary_key=True, default=lambda: secrets.token_hex(8))
    account_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="メイン口座")
    balance = Column(Integer, default=10000)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    owner = relationship("UserDB", back_populates="wallets")


class ContractDB(Base):
    __tablename__ = "contracts"

    id = Column(String, primary_key=True, default=lambda: secrets.token_hex(8))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String, default="OPEN")
    creator_id = Column(String, ForeignKey("users.id"), nullable=False)
    creator_wallet_id = Column(String, ForeignKey("wallets.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ==========================================
# 3. Pydantic スキーマ
# ==========================================
class UserCreate(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class WalletResponse(BaseModel):
    id: str
    account_number: str
    name: str
    balance: int

    class Config:
        from_attributes = True

class ContractCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    amount: int = Field(..., gt=0)
    creator_wallet_id: str

class ContractResponse(BaseModel):
    id: str
    title: str
    description: str
    amount: int
    status: str
    creator_id: str
    creator_wallet_id: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==========================================
# 4. ヘルパー関数 & 依存性注入
# ==========================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async function get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証トークンが無効または期限切れです。",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

# ==========================================
# 5. エンドポイント
# ==========================================
@app.post("/api/auth/register")
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(UserDB).filter(UserDB.username == user_in.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="このユーザー名は既に使用されています。")

    new_user = UserDB(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    default_wallet = WalletDB(
        account_number="MW-" + secrets.token_hex(3).upper(),
        name="メイン口座",
        balance=10000,
        user_id=new_user.id
    )
    db.add(default_wallet)
    db.commit()

    return {"message": "ユーザー登録が完了しました。"}

@app.post("/api/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザー名またはパスワードが違います。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.id})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/wallets/me", response_model=List[WalletResponse])
def get_my_wallets(current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(WalletDB).filter(WalletDB.user_id == current_user.id).all()

@app.post("/api/contracts", status_code=201)
def create_contract(
    contract_in: ContractCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wallet = db.query(WalletDB).filter(
        WalletDB.id == contract_in.creator_wallet_id,
        WalletDB.user_id == current_user.id
    ).first()

    if not wallet:
        raise HTTPException(
            status_code=400,
            detail="指定された支払口座が存在しないか、所有権がありません。"
        )

    if wallet.balance < contract_in.amount:
        raise HTTPException(
            status_code=400,
            detail=f"口座残高が不足しています。（現在残高: {wallet.balance}）"
        )

    new_contract = ContractDB(
        title=contract_in.title,
        description=contract_in.description,
        amount=contract_in.amount,
        creator_id=current_user.id,
        creator_wallet_id=wallet.id,
        status="OPEN"
    )

    db.add(new_contract)
    db.commit()
    db.refresh(new_contract)

    return {"message": "市場に契約書を掲示しました！", "contract_id": new_contract.id}

@app.get("/api/contracts", response_model=List[ContractResponse])
def list_contracts(db: Session = Depends(get_db)):
    return db.query(ContractDB).order_by(ContractDB.created_at.desc()).all()
