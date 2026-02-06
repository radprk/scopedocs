"""Rate limiting middleware."""

import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from functools import wraps

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.config import get_settings


@dataclass
class RateLimitState:
    """Rate limit state for a client."""
    requests: int = 0
    window_start: float = field(default_factory=time.time)


class RateLimiter:
    """Simple in-memory rate limiter (use Redis in production for multi-instance)."""
    
    def __init__(self, requests_per_window: int = 100, window_seconds: int = 60):
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._states: Dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._lock = asyncio.Lock()
    
    def _get_client_key(self, request: Request) -> str:
        """Get a unique key for the client."""
        # Use forwarded IP if behind proxy, otherwise use client host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        return f"rate_limit:{ip}"
    
    async def is_allowed(self, request: Request) -> tuple[bool, Dict[str, str]]:
        """Check if request is allowed and return rate limit headers."""
        key = self._get_client_key(request)
        now = time.time()
        
        async with self._lock:
            state = self._states[key]
            
            # Reset window if expired
            if now - state.window_start >= self.window_seconds:
                state.requests = 0
                state.window_start = now
            
            # Check limit
            remaining = self.requests_per_window - state.requests
            reset_time = int(state.window_start + self.window_seconds)
            
            headers = {
                "X-RateLimit-Limit": str(self.requests_per_window),
                "X-RateLimit-Remaining": str(max(0, remaining - 1)),
                "X-RateLimit-Reset": str(reset_time),
            }
            
            if state.requests >= self.requests_per_window:
                headers["Retry-After"] = str(reset_time - int(now))
                return False, headers
            
            state.requests += 1
            return True, headers
    
    async def cleanup_expired(self):
        """Remove expired states to prevent memory leaks."""
        now = time.time()
        async with self._lock:
            expired = [
                key for key, state in self._states.items()
                if now - state.window_start >= self.window_seconds * 2
            ]
            for key in expired:
                del self._states[key]


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RateLimiter(
            requests_per_window=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window,
        )
    return _rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to apply rate limiting to all requests."""
    
    # Paths to exclude from rate limiting
    EXCLUDED_PATHS = {"/health", "/", "/docs", "/openapi.json"}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)
        
        limiter = get_rate_limiter()
        allowed, headers = await limiter.is_allowed(request)
        
        if not allowed:
            response = Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
            for key, value in headers.items():
                response.headers[key] = value
            return response
        
        response = await call_next(request)
        
        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value
        
        return response


def rate_limiter(requests: int = 10, window: int = 60):
    """Decorator for per-endpoint rate limiting."""
    limiter = RateLimiter(requests_per_window=requests, window_seconds=window)
    
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            allowed, headers = await limiter.is_allowed(request)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers=headers,
                )
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator
