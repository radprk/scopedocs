"""Authentication routes."""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional

from backend.storage.postgres import (
    create_user, get_user_by_email, get_user_workspaces
)
from backend.config import get_settings
from backend.auth.jwt_auth import (
    create_access_token, get_current_user, AuthUser
)
from backend.auth.password import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


# =============================================================================
# Models
# =============================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    workspaces: list


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/register", response_model=UserResponse)
async def register(request: RegisterRequest):
    """Register a new user."""
    existing = await get_user_by_email(request.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    password_hashed = hash_password(request.password)
    user = await create_user(request.email, password_hashed, request.name)
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        workspaces=[]
    )


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Login and get access token."""
    user = await get_user_by_email(request.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    workspace_ids = await get_user_workspaces(user["id"])
    
    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        workspace_ids=workspace_ids,
        is_admin=user["is_admin"],
    )
    
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiration_hours * 3600
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: AuthUser = Depends(get_current_user)):
    """Get current user info."""
    return UserResponse(
        id=user.user_id,
        email=user.email,
        name=None,
        workspaces=user.workspace_ids
    )
