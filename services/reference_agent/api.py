from fastapi import APIRouter

from .llm import ask_gpt
from .schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["AI"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Chat endpoint for interacting with the AI agent.
    The AI may return:
      - A normal text response
      - A tool execution result
    """

    result = ask_gpt(request.message)

    return ChatResponse(
        response=result
    )