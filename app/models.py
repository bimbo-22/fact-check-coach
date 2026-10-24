"""Pydantic request/response schemas for the public API."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Verdict = Literal["true", "false", "misleading", "unverified", "developing", "opinion"]
Confidence = Literal["high", "medium", "low"]
Stance = Literal["supports", "contradicts", "not_mentioned"]
Guess = Literal["true", "false", "not_sure"]

MAX_INPUT_CHARS = 2000
DISCLAIMER = "Based only on the sources shown. Check them yourself."


class CheckRequest(BaseModel):
    text: str = ""
    url: str | None = None
    image_base64: str | None = None  # a screenshot; only its text is used, the image is never stored
    image_url: str | None = None     # Instagram/Facebook CDN images only
    client: Literal["telegram", "extension", "script"] = "script"

    @field_validator("text")
    @classmethod
    def truncate(cls, v: str) -> str:
        # Long posts are truncated, never rejected.
        return v.strip()[:MAX_INPUT_CHARS]

    @model_validator(mode="after")
    def needs_something(self) -> "CheckRequest":
        if not self.text and not (self.url and self.url.strip()) and not self.image_base64 and not self.image_url:
            raise ValueError("Send the post text, a link or a screenshot.")
        return self


class StartResponse(BaseModel):
    check_id: str | None
    claim: str | None
    checkable: bool
    question: str | None
    guess_options: list[Guess] = ["true", "false", "not_sure"]
    note: str | None = None
    needs_text: bool = False


class RevealRequest(BaseModel):
    check_id: str
    guess: Guess


class Agreement(BaseModel):
    supports: int = 0
    contradicts: int = 0
    not_mentioned: int = 0
    outlets_checked: int = 0
    rejected_quotes: int = 0


class SourceOut(BaseModel):
    title: str
    url: str
    outlet: str
    domain: str
    stance: Stance
    quote: str | None = None
    is_claimreview: bool = False
    rating: str | None = None


class RevealResponse(BaseModel):
    verdict: Verdict
    confidence: Confidence
    claim: str | None
    explanation: str
    agreement: Agreement
    sources: list[SourceOut] = Field(default_factory=list)
    guess_feedback: str | None = None
    tip: str
    disclaimer: str = DISCLAIMER


class CommentsRequest(BaseModel):
    text: str = ""
    image_base64: str | None = None
    client: Literal["telegram", "extension", "script"] = "script"

    @field_validator("text")
    @classmethod
    def truncate(cls, v: str) -> str:
        return v.strip()[:MAX_INPUT_CHARS * 2]

    @model_validator(mode="after")
    def needs_something(self) -> "CommentsRequest":
        if not self.text and not self.image_base64:
            raise ValueError("Paste the comments or send a screenshot of them.")
        return self


CommentKind = Literal["opinion", "claim", "question", "other"]


class CommentOut(BaseModel):
    text: str
    kind: CommentKind
    label: str
    claim: str | None = None  # the underlying claim, stated positively
    denies: bool = False      # the comment rejects that claim; `verdict` is about the comment itself
    verdict: Verdict | None = None
    confidence: Confidence | None = None
    source: SourceOut | None = None


class CommentsSummary(BaseModel):
    opinions: int = 0
    questions: int = 0
    claims: int = 0
    misinformation: int = 0
    backed: int = 0
    unchecked_claims: int = 0


class CommentsResponse(BaseModel):
    comments: list[CommentOut] = Field(default_factory=list)
    summary: CommentsSummary = Field(default_factory=CommentsSummary)
    tip: str = ""
    note: str | None = None
    disclaimer: str = DISCLAIMER
