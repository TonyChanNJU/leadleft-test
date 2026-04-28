"""Chat/Q&A router."""

import logging
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, Citation
from app.services.query_engine import query_documents
from app.services.llm_provider import SUPPORTED_MODELS

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/chat/models")
async def get_models():
    """Get list of dynamically available models based on configured API keys."""
    from app.services.llm_provider import get_available_models
    api_keys = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
        "deepseek": settings.deepseek_api_key,
    }
    return {"models": get_available_models(api_keys)}

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Ask a question about uploaded documents."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    model_id = request.model or settings.default_llm_model
    if model_id not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model: {model_id}. Supported: {list(SUPPORTED_MODELS.keys())}"
        )

    api_keys = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
        "deepseek": settings.deepseek_api_key,
    }

    try:
        result = await query_documents(
            question=request.question,
            doc_ids=request.doc_ids,
            model_id=model_id,
            api_keys=api_keys,
        )

        return ChatResponse(
            answer=result["answer"],
            citations=[
                Citation(
                    page_num=c["page_num"],
                    text=c["text"],
                    filename=c["filename"],
                    doc_id=c["doc_id"]
                )
                for c in result.get("citations", [])
            ],
            model_used=result["model_used"],
        )
    except Exception as e:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))

