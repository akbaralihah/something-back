import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user import UserRepository


class UserService:
    def __init__(self, db: AsyncSession):
        self.repo = UserRepository(db)

    async def get_all(self, page: int, page_size: int):
        users, total = await self.repo.get_all(page=page, page_size=page_size)
        return {
            "items": users,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size),
        }

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.repo.get_by_id(user_id=user_id)

    async def update(self, user_id: int, data: dict) -> User | None:
        user = await self.repo.get_by_id(user_id=user_id)
        if not user:
            return None
        return await self.repo.update(user=user, data=data)
