"""
Pydantic schemas for the Web3Geeks client onboarding agent API.
"""
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


class OnboardRequest(BaseModel):
    """Incoming request to kick off a new client onboarding / proposal run."""
    company_name: str
    contact_email: EmailStr
    project_description: str
    budget_range_usd: str  # e.g. "5000-10000"
    timeline_weeks: int

    @field_validator("company_name")
    @classmethod
    def company_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("company_name must not be empty")
        return v.strip()

    @field_validator("project_description")
    @classmethod
    def description_min_length(cls, v: str) -> str:
        if not v or len(v.strip()) < 10:
            raise ValueError("project_description must be at least 10 characters")
        return v.strip()

    @field_validator("timeline_weeks")
    @classmethod
    def timeline_positive(cls, v: int) -> int:
        if v <= 0 or v > 104:
            raise ValueError("timeline_weeks must be between 1 and 104")
        return v


class OnboardResponse(BaseModel):
    """Response returned once a run reaches a stopping point (approval needed or done)."""
    thread_id: str
    status: str  # "awaiting_approval" | "completed" | "failed"
    message: str
    proposal_preview: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


class ApprovalRequest(BaseModel):
    """Human decision on a pending proposal."""
    thread_id: str
    approved: bool
    feedback: Optional[str] = None  # required if approved=False, used to trigger a revision
