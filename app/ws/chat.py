from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.user import UserRepository
from app.schemas.chat import MessageRead
from app.services.chat import ChatError, ChatService
from app.utils.jwt import decode_access_token
from app.ws.manager import manager

router = APIRouter()


async def _handle_incoming(
    service: ChatService, user_id: int, data: dict, websocket: WebSocket
) -> None:
    if not isinstance(data, dict) or data.get("action") != "send_message":
        await websocket.send_json({"type": "error", "detail": "Unknown action."})
        return

    chat_id = data.get("chat_id")
    text = data.get("text")
    if not isinstance(chat_id, int) or not isinstance(text, str) or not text.strip():
        await websocket.send_json(
            {"type": "error", "detail": "chat_id and text are required."}
        )
        return

    result = await service.send_message(sender_id=user_id, chat_id=chat_id, text=text)
    if isinstance(result, ChatError):
        await websocket.send_json({"type": "error", "detail": result.detail})
        return

    message, member_ids = result
    payload = {
        "type": "message",
        "data": MessageRead.model_validate(message).model_dump(mode="json"),
    }
    for member_id in member_ids:
        await manager.send_to_user(member_id, payload)


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = decode_access_token(token)
    user = await UserRepository(db).get_by_id(user_id) if user_id is not None else None
    if user is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await websocket.accept()
    manager.connect(user.id, websocket)
    service = ChatService(db)

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON payload."}
                )
                continue

            await _handle_incoming(service, user.id, data, websocket)
    finally:
        manager.disconnect(user.id, websocket)
