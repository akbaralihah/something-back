from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_verification import PhoneVerification

CODE_TTL_MINUTES = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PhoneVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, phone_number: str, code: str) -> PhoneVerification:
        record = PhoneVerification(
            phone_number=phone_number,
            code=code,
            expires_at=_utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
            is_verified=False,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_latest_pending(
        self, phone_number: str, code: str
    ) -> PhoneVerification | None:
        result = await self.session.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.phone_number == phone_number,
                PhoneVerification.code == code,
                PhoneVerification.is_verified.is_(False),
                PhoneVerification.expires_at > _utcnow(),
            )
            .order_by(PhoneVerification.id.desc())
        )
        return result.scalars().first()

    async def get_latest_verified(self, phone_number: str) -> PhoneVerification | None:
        result = await self.session.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.phone_number == phone_number,
                PhoneVerification.is_verified.is_(True),
                PhoneVerification.expires_at > _utcnow(),
            )
            .order_by(PhoneVerification.id.desc())
        )
        return result.scalars().first()

    async def mark_verified(self, record: PhoneVerification) -> PhoneVerification:
        record.is_verified = True
        await self.session.commit()
        await self.session.refresh(record)
        return record
