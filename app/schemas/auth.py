import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    site_id: uuid.UUID
    role: Role


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    is_superadmin: bool
    memberships: list[MembershipOut]


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    is_superadmin: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None
    is_superadmin: bool
    is_active: bool


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    is_active: bool | None = None
    is_superadmin: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
