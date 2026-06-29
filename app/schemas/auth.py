from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_name: str
    user_role: str


class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[str] = None
