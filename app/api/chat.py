from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatCreate, ChatDetail, ChatMemberRead, ChatRead, MessageRead
from app.schemas.pagination import PaginatedResponse
from app.services.chat import ChatError, ChatService

router = APIRouter(prefix="/chats", tags=["chats"])

_ERROR_STATUS = {
    ChatError.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ChatError.NOT_A_MEMBER: status.HTTP_403_FORBIDDEN,
    ChatError.CHANNEL_WRITE_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ChatError.INVALID_MEMBER: status.HTTP_400_BAD_REQUEST,
}


def _raise_for_error(error: ChatError) -> None:
    raise HTTPException(status_code=_ERROR_STATUS[error], detail=error.detail)


@router.post("", response_model=ChatRead, summary="Create or get a chat")
@limiter.limit("20/minute")
async def create_chat(
    request: Request,
    response: Response,
    body: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.create_chat(
        creator_id=current_user.id,
        type_=body.type,
        title=body.title,
        member_ids=body.member_ids,
    )
    if isinstance(result, ChatError):
        _raise_for_error(result)

    chat, created = result
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return chat


@router.get("", response_model=PaginatedResponse[ChatRead], summary="List of my chats")
@limiter.limit("30/minute")
async def list_chats(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100, description="Quantity per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    return await service.list_user_chats(
        user_id=current_user.id, page=page, page_size=page_size
    )


@router.get("/{chat_id}", response_model=ChatDetail, summary="Chat details and members")
@limiter.limit("30/minute")
async def get_chat(
    request: Request,
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.get_chat_detail(chat_id=chat_id, user_id=current_user.id)
    if isinstance(result, ChatError):
        _raise_for_error(result)

    chat, members = result
    return ChatDetail(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        created_by=chat.created_by,
        created_at=chat.created_at,
        members=[ChatMemberRead.model_validate(member) for member in members],
    )


@router.get(
    "/{chat_id}/messages",
    response_model=PaginatedResponse[MessageRead],
    summary="Chat message history",
)
@limiter.limit("30/minute")
async def list_messages(
    request: Request,
    chat_id: int,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Quantity per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.list_messages(
        chat_id=chat_id, user_id=current_user.id, page=page, page_size=page_size
    )
    if isinstance(result, ChatError):
        _raise_for_error(result)
    return result
