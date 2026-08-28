from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_all(self, page: int, page_size: int) -> tuple[list[User], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            select(func.count()).select_from(User)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(User).offset(offset).limit(page_size)
        )
        return list(result.scalars().all()), total

    async def update(self, user: User, data: dict) -> User:
        for field, value in data.items():
            setattr(user, field, value)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_phone_number(self, phone_number: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    async def create_from_phone(
        self, phone_number: str, first_name: str, last_name: str
    ) -> User:
        user = User(
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
