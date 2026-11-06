from pydantic import BaseModel, EmailStr


class PersonIn(BaseModel):
    """Who to look up. A body, not a query string, so the address stays out of access logs."""

    email: EmailStr


class PersonSummary(BaseModel):
    items: int


class ErasureResult(BaseModel):
    deleted: int
