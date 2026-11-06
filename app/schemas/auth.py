import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MfaRequired(BaseModel):
    """Login answer when the password was right but a second factor is still needed."""

    mfa_required: bool = True
    mfa_token: str


class MfaLogin(BaseModel):
    mfa_token: str = Field(max_length=2048)
    code: str = Field(min_length=1, max_length=32)  # authenticator code or recovery code


class TotpSetup(BaseModel):
    secret: str
    uri: str


class TotpConfirm(BaseModel):
    """Turning TOTP on: the password (so a stolen session can't lock the owner out) and the first code."""

    password: str = Field(max_length=256)
    code: str = Field(min_length=1, max_length=32)


class TotpProof(BaseModel):
    """Re-authentication for turning TOTP off or replacing the recovery codes."""

    password: str = Field(max_length=256)
    code: str = Field(min_length=1, max_length=32)


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


class TotpEnabled(TokenResponse, RecoveryCodes):
    pass


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
    totp_enabled: bool
    recovery_codes_left: int
    memberships: list[MembershipOut]


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class FeaturesOut(BaseModel):
    password_reset: bool


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
    totp_enabled: bool


class UserPage(BaseModel):
    items: list[UserOut]
    total: int


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    is_active: bool | None = None
    is_superadmin: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
