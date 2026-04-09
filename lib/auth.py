import os
import uuid
from datetime import datetime, timedelta
import jwt
import bcrypt
from fastapi import Request, HTTPException

JWT_SECRET = os.environ.get("JWT_SECRET", "job-hunter-ai-jwt-secret-change-me")
COOKIE_NAME = "auth_token"
TOKEN_EXPIRY_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str, username: str) -> str:
    payload = {
        "id": user_id,
        "username": username,
        "exp": datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_token(token)


def generate_user_id() -> str:
    return str(uuid.uuid4())
