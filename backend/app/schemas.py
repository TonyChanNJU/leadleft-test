"""Pydantic models for the API."""

from pydantic import BaseModel

class ChatRequest(BaseModel):
    """Chat request model."""
    question: str
    doc_ids: list[str] = []  # Empty = search all documents
    model: str = ""  # Empty = use default model


class Citation(BaseModel):
    """A source citation from the document."""
    page_num: int
    text: str
    filename: str
    doc_id: str


class ChatResponse(BaseModel):
    """Chat response model."""
    answer: str
    citations: list[Citation] = []
    model_used: str = ""
