"""
Auth routes: /auth/register and /auth/login
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..auth import authenticate_user, create_access_token, create_user

router = APIRouter(tags=["Authentication"])


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest):
    """Register a new user and return a JWT token."""
    try:
        user = create_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    token = create_access_token(subject=user.email)
    return TokenResponse(access_token=token, email=user.email)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    """Authenticate and return a JWT token."""
    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.email)
    return TokenResponse(access_token=token, email=user.email)
