"""routers/auth.py — 로그인(평문 계정 비교, 기존 Streamlit 방식과 동일하게 유지)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import USERS

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    role: str


class LoginResponse(BaseModel):
    username: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = USERS.get(req.username)
    if not user or user["password"] != req.password or user["role"] != req.role:
        raise HTTPException(status_code=401, detail="아이디, 비밀번호 또는 구분이 올바르지 않습니다.")
    return LoginResponse(username=req.username, role=user["role"])
