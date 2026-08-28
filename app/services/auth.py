import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.phone_verification import PhoneVerificationRepository
from app.repositories.user import UserRepository
from app.utils.jwt import create_access_token


class AuthService:
    def __init__(self, db: AsyncSession):
        self.phone_repo = PhoneVerificationRepository(db)
        self.user_repo = UserRepository(db)

    async def send_code(self, phone_number: str) -> str:
        code = f"{random.randint(0, 9999):04d}"
        await self.phone_repo.create(phone_number=phone_number, code=code)
        return code

    async def verify_code(
        self, phone_number: str, code: str
    ) -> tuple[bool, User | None, str | None] | None:
        record = await self.phone_repo.get_latest_pending(phone_number, code)
        if record is None:
            return None

        await self.phone_repo.mark_verified(record)

        user = await self.user_repo.get_by_phone_number(phone_number)
        if user is None:
            return True, None, None

        token = create_access_token(user.id)
        return False, user, token

    async def complete_profile(
        self, phone_number: str, first_name: str, last_name: str
    ) -> tuple[User, str] | None:
        verified = await self.phone_repo.get_latest_verified(phone_number)
        if verified is None:
            return None

        existing = await self.user_repo.get_by_phone_number(phone_number)
        if existing is not None:
            return None

        user = await self.user_repo.create_from_phone(
            phone_number=phone_number, first_name=first_name, last_name=last_name
        )
        token = create_access_token(user.id)
        return user, token
