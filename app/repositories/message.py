from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chat_id: int, sender_id: int, text: str) -> Message:
        message = Message(chat_id=chat_id, sender_id=sender_id, text=text)
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def list_for_chat(
        self, chat_id: int, page: int, page_size: int
    ) -> tuple[list[Message], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total
