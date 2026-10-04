"""Chat conversation endpoints (sync + SSE streaming)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_agent_repo, get_chat_service, get_settings
from app.config import Settings
from app.models.conversation import (
    ChatAttachment,
    Conversation,
    ConversationCreateResponse,
    ConversationSummary,
    ConversationUpdate,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services.chat_attachments import (
    ChatAttachmentError,
    mirror_into_agent_workspace,
    save_upload,
)
from app.services.chat_service import ChatService, ChatServiceError
from app.services.repos import AgentRepository

router = APIRouter(tags=["chats"])


class CancelResponse(BaseModel):
    ok: bool
    message: str


class HandoffRequest(BaseModel):
    message_index: Optional[int] = None
    handoff_agent_id: Optional[str] = None


class MarkReadResponse(BaseModel):
    ok: bool
    last_read_at: Optional[str] = None


def _chat_http_status(detail: str) -> int:
    lower = detail.lower()
    if "not found" in lower:
        return 404
    if "timed out" in lower:
        return 504
    if "required" in lower:
        return 400
    return 502


def _sse_pack(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post(
    "/agents/{agent_id}/chats",
    response_model=ConversationCreateResponse,
    status_code=201,
)
async def create_chat(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    chat_service: ChatService = Depends(get_chat_service),
) -> ConversationCreateResponse:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    conversation = await chat_service.create_chat(agent_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ConversationCreateResponse(id=conversation.id)


@router.get(
    "/agents/{agent_id}/chats",
    response_model=list[ConversationSummary],
)
async def list_chats(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    chat_service: ChatService = Depends(get_chat_service),
) -> list[ConversationSummary]:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await chat_service.list_chats(agent_id)


@router.get("/chats", response_model=list[ConversationSummary])
async def list_all_chats(
    limit: int = Query(100, ge=1, le=500),
    chat_service: ChatService = Depends(get_chat_service),
) -> list[ConversationSummary]:
    return await chat_service.list_all_chats(limit=limit)


@router.get("/chats/{chat_id}", response_model=Conversation)
async def get_chat(
    chat_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> Conversation:
    conversation = await chat_service.get_chat(chat_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return conversation


@router.get("/chats/{chat_id}/messages/{msg_index}/html", response_class=HTMLResponse)
async def get_message_html(
    chat_id: str,
    msg_index: int,
    chat_service: ChatService = Depends(get_chat_service),
) -> HTMLResponse:
    """Serve a single message's HTML report for iframe `src` (reliable preview)."""
    conversation = await chat_service.get_chat(chat_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if msg_index < 0 or msg_index >= len(conversation.messages):
        raise HTTPException(status_code=404, detail="Message not found")
    html = conversation.messages[msg_index].html
    if not html:
        raise HTTPException(status_code=404, detail="Message has no HTML report")
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


@router.post("/chats/{chat_id}/attachments", response_model=ChatAttachment, status_code=201)
async def upload_chat_attachment(
    chat_id: str,
    file: UploadFile = File(...),
    chat_service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> ChatAttachment:
    conversation = await chat_service.get_chat(chat_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    data = await file.read()
    try:
        attachment = save_upload(
            settings.workspace_path,
            chat_id,
            filename=file.filename or "upload.bin",
            data=data,
            content_type=file.content_type,
        )
        mirror_into_agent_workspace(
            settings.workspace_path,
            conversation.agent_id,
            chat_id,
            attachment,
        )
    except ChatAttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await chat_service.add_attachment(chat_id, attachment)
    if updated is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return attachment


@router.post("/chats/{chat_id}/read", response_model=MarkReadResponse)
async def mark_chat_read(
    chat_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> MarkReadResponse:
    conversation = await chat_service.mark_read(chat_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    ts = conversation.last_read_at.isoformat() if conversation.last_read_at else None
    return MarkReadResponse(ok=True, last_read_at=ts)


@router.post("/chats/{chat_id}/handoff", response_model=Conversation)
async def handoff_chat_report(
    chat_id: str,
    body: HandoffRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> Conversation:
    try:
        return await chat_service.handoff_report(
            chat_id,
            message_index=body.message_index,
            handoff_agent_id=body.handoff_agent_id,
        )
    except ChatServiceError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_chat_http_status(detail), detail=detail) from exc


@router.patch("/chats/{chat_id}", response_model=Conversation)
async def update_chat(
    chat_id: str,
    body: ConversationUpdate,
    chat_service: ChatService = Depends(get_chat_service),
) -> Conversation:
    try:
        conversation = await chat_service.rename_chat(chat_id, body.title)
    except ChatServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return conversation


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> Response:
    deleted = await chat_service.delete_chat(chat_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    return Response(status_code=204)


@router.post("/chats/{chat_id}/messages", response_model=SendMessageResponse)
async def send_message(
    chat_id: str,
    body: SendMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SendMessageResponse:
    try:
        conversation = await chat_service.send_message(chat_id, body.content)
    except ChatServiceError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_chat_http_status(detail), detail=detail) from exc

    assistant = next(
        (m for m in reversed(conversation.messages) if m.role.value == "assistant"),
        None,
    )
    if assistant is None:
        raise HTTPException(status_code=502, detail="No assistant reply produced")
    return SendMessageResponse(
        messages=conversation.messages,
        assistant_message=assistant,
    )


@router.post("/chats/{chat_id}/messages/stream")
async def send_message_stream(
    chat_id: str,
    body: SendMessageRequest,
    request: Request,
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """SSE stream of token/tool/done/error events (admin UI default)."""

    async def event_gen() -> AsyncIterator[str]:
        try:
            async for item in chat_service.stream_message(chat_id, body.content):
                if await request.is_disconnected():
                    await chat_service.request_cancel(chat_id)
                    break
                event = str(item.get("event") or "message")
                data = item.get("data") or {}
                # Alias: clients may listen for either token or delta.
                if event == "token":
                    yield _sse_pack("token", data)
                    yield _sse_pack("delta", data)
                else:
                    yield _sse_pack(event, data)
        except Exception as exc:  # noqa: BLE001
            yield _sse_pack("error", {"message": str(exc) or "Stream failed"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chats/{chat_id}/cancel", response_model=CancelResponse)
async def cancel_chat(
    chat_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> CancelResponse:
    conversation = await chat_service.get_chat(chat_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    ok = await chat_service.request_cancel(chat_id)
    if ok:
        return CancelResponse(ok=True, message="Cancel requested")
    return CancelResponse(ok=False, message="No in-flight chat stream for this id")
