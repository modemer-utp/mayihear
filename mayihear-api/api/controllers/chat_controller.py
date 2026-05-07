from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from application.handlers.chat_handler import chat_with_transcript

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str   # "user" or "model"
    content: str


class ChatRequest(BaseModel):
    transcript: str
    history: List[ChatMessage] = []
    message: str


@router.post("/message")
async def send_chat_message(request: ChatRequest):
    if not request.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript is required")
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    try:
        history = [{"role": m.role, "content": m.content} for m in request.history]
        response = chat_with_transcript(request.transcript, history, request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
