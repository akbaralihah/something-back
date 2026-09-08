import enum
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, ChatMember, ChatRole, ChatType, Message
from app.repositories.chat import ChatRepository
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository


class ChatError(str, enum.Enum):
    NOT_FOUND = "not_found"
    NOT_A_MEMBER = "not_a_member"
    CHANNEL_WRITE_FORBIDDEN = "channel_write_forbidden"
    INVALID_MEMBER = "invalid_member"

    @property
    def detail(self) -> str:
        return {
            ChatError.NOT_FOUND: "Chat not found.",
            ChatError.NOT_A_MEMBER: "You are not a member of this chat.",
            ChatError.CHANNEL_WRITE_FORBIDDEN: "Only the channel owner can send messages.",
            ChatError.INVALID_MEMBER: (
                "member_ids must reference existing users other than yourself."
            ),
        }[self]


def _paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size),
    }


class ChatService:
    def __init__(self, db: AsyncSession):
        self.chat_repo = ChatRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)

    async def create_chat(
        self, creator_id: int, type_: ChatType, title: str | None, member_ids: list[int]
    ) -> tuple[Chat, bool] | ChatError:
        for user_id in member_ids:
            if user_id == creator_id:
                return ChatError.INVALID_MEMBER
            if await self.user_repo.get_by_id(user_id) is None:
                return ChatError.INVALID_MEMBER

        if type_ == ChatType.PRIVATE:
            other_id = member_ids[0]
            existing = await self.chat_repo.get_private_between(creator_id, other_id)
            if existing is not None:
                return existing, False
            chat = await self.chat_repo.create(type_, None, creator_id, [other_id])
            return chat, True

        chat = await self.chat_repo.create(type_, title, creator_id, member_ids)
        return chat, True

    async def get_chat_detail(
        self, chat_id: int, user_id: int
    ) -> tuple[Chat, list[ChatMember]] | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND
        if await self.chat_repo.get_membership(chat_id, user_id) is None:
            return ChatError.NOT_A_MEMBER
        members = await self.chat_repo.list_members(chat_id)
        return chat, members

    async def list_user_chats(self, user_id: int, page: int, page_size: int) -> dict:
        chats, total = await self.chat_repo.list_for_user(user_id, page, page_size)
        return _paginate(chats, total, page, page_size)

    async def list_messages(
        self, chat_id: int, user_id: int, page: int, page_size: int
    ) -> dict | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND
        if await self.chat_repo.get_membership(chat_id, user_id) is None:
            return ChatError.NOT_A_MEMBER
        messages, total = await self.message_repo.list_for_chat(chat_id, page, page_size)
        return _paginate(messages, total, page, page_size)

    async def send_message(
        self, sender_id: int, chat_id: int, text: str
    ) -> tuple[Message, list[int]] | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND

        membership = await self.chat_repo.get_membership(chat_id, sender_id)
        if membership is None:
            return ChatError.NOT_A_MEMBER

        if chat.type == ChatType.CHANNEL and membership.role != ChatRole.OWNER:
            return ChatError.CHANNEL_WRITE_FORBIDDEN

        message = await self.message_repo.create(chat_id, sender_id, text)
        members = await self.chat_repo.list_members(chat_id)
        return message, [member.user_id for member in members]
