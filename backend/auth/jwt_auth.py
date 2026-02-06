"""JWT authentication for API endpoints."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

# Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", "24"))

security = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    """Authenticated user information."""
    user_id: str
    email: str
    workspace_ids: List[str]  # Workspaces user has access to
    is_admin: bool = False
    
    def has_workspace_access(self, workspace_id: str) -> bool:
        """Check if user has access to a workspace."""
        return self.is_admin or workspace_id in self.workspace_ids


def create_access_token(
    user_id: str,
    email: str,
    workspace_ids: List[str],
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)
    
    expire = datetime.now(timezone.utc) + expires_delta
    
    payload = {
        "sub": user_id,
        "email": email,
        "workspace_ids": workspace_ids,
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[AuthUser]:
    """Verify a JWT token and return user info."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return AuthUser(
            user_id=payload["sub"],
            email=payload["email"],
            workspace_ids=payload.get("workspace_ids", []),
            is_admin=payload.get("is_admin", False),
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthUser:
    """Get current authenticated user (required)."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[AuthUser]:
    """Get current user if authenticated, None otherwise."""
    if credentials is None:
        return None
    return verify_token(credentials.credentials)


def require_workspace_access(workspace_id: str):
    """Dependency to require access to a specific workspace."""
    async def check_access(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not user.has_workspace_access(workspace_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No access to workspace {workspace_id}",
            )
        return user
    return check_access


class WorkspaceAccessChecker:
    """Callable dependency for workspace access checking."""
    
    def __init__(self, workspace_id_param: str = "workspace_id"):
        self.workspace_id_param = workspace_id_param
    
    async def __call__(
        self,
        user: AuthUser = Depends(get_current_user),
        **kwargs,
    ) -> AuthUser:
        workspace_id = kwargs.get(self.workspace_id_param)
        if workspace_id and not user.has_workspace_access(workspace_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No access to workspace {workspace_id}",
            )
        return user
