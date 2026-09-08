from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.chat import Chat, ChatMember, ChatRole, ChatType


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, chat_id: int) -> Chat | None:
        result = await self.session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    async def get_private_between(self, user_a: int, user_b: int) -> Chat | None:
        cm1 = aliased(ChatMember)
        cm2 = aliased(ChatMember)
        result = await self.session.execute(
            select(Chat)
            .join(cm1, cm1.chat_id == Chat.id)
            .join(cm2, cm2.chat_id == Chat.id)
            .where(
                Chat.type == ChatType.PRIVATE,
                cm1.user_id == user_a,
                cm2.user_id == user_b,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, type_: ChatType, title: str | None, creator_id: int, member_ids: list[int]
    ) -> Chat:
        chat = Chat(type=type_, title=title, created_by=creator_id)
        self.session.add(chat)
        await self.session.flush()

        members = [ChatMember(chat_id=chat.id, user_id=creator_id, role=ChatRole.OWNER)]
        members += [
            ChatMember(chat_id=chat.id, user_id=user_id, role=ChatRole.MEMBER)
            for user_id in member_ids
        ]
        self.session.add_all(members)
        await self.session.commit()
        await self.session.refresh(chat)
        return chat

    async def get_membership(self, chat_id: int, user_id: int) -> ChatMember | None:
        result = await self.session.execute(
            select(ChatMember).where(
                ChatMember.chat_id == chat_id, ChatMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, chat_id: int) -> list[ChatMember]:
        result = await self.session.execute(
            select(ChatMember).where(ChatMember.chat_id == chat_id)
        )
        return list(result.scalars().all())

    async def list_for_user(
        self, user_id: int, page: int, page_size: int
    ) -> tuple[list[Chat], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            select(func.count())
            .select_from(ChatMember)
            .where(ChatMember.user_id == user_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Chat)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .where(ChatMember.user_id == user_id)
            .order_by(Chat.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total
