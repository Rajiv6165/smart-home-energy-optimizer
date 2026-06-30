"""
Auth routes: /auth/register, /auth/login, /auth/profile and /auth/change-password
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import Dict, Any

from ..auth import authenticate_user, create_access_token, create_user, get_current_user, get_password_hash, verify_password
from ..database import session_scope
from ..models import User
from ..schemas import ResponseEnvelope, UserProfileResponse, UserProfileUpdate, ChangePasswordRequest

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


@router.get("/profile", response_model=ResponseEnvelope[UserProfileResponse])
def get_profile(current_user: User = Depends(get_current_user)):
    """Retrieve settings profile for the authenticated user."""
    return {"data": current_user}


@router.put("/profile", response_model=ResponseEnvelope[UserProfileResponse])
def update_profile(payload: UserProfileUpdate, current_user: User = Depends(get_current_user)):
    """Update profile and comfort preferences for the authenticated user."""
    with session_scope() as session:
        # Fetch fresh object inside session
        db_user = session.get(User, current_user.id)
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update fields
        for field, value in payload.dict(exclude_unset=True).items():
            setattr(db_user, field, value)

        session.add(db_user)
        session.commit()
        session.refresh(db_user)
        return {"data": db_user}


@router.post("/change-password", response_model=ResponseEnvelope[Dict[str, Any]])
def change_password(payload: ChangePasswordRequest, current_user: User = Depends(get_current_user)):
    """Securely change the user's password."""
    with session_scope() as session:
        db_user = session.get(User, current_user.id)
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if not verify_password(payload.old_password, db_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password")

        db_user.hashed_password = get_password_hash(payload.new_password)
        session.add(db_user)
        session.commit()
        return {"data": {"success": True, "message": "Password changed successfully."}}
