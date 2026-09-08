from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserPhoto


class UserPhotoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, photo_url: str) -> UserPhoto:
        photo = UserPhoto(user_id=user_id, photo_url=photo_url)
        self.session.add(photo)
        await self.session.commit()
        await self.session.refresh(photo)
        return photo

    async def get_by_id(self, photo_id: int) -> UserPhoto | None:
        result = await self.session.execute(
            select(UserPhoto).where(UserPhoto.id == photo_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: int) -> list[UserPhoto]:
        result = await self.session.execute(
            select(UserPhoto).where(UserPhoto.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_last_by_user_id(self, user_id: int) -> UserPhoto | None:
        result = await self.session.execute(
            select(UserPhoto)
            .where(UserPhoto.user_id == user_id)
            .order_by(UserPhoto.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update(self, photo: UserPhoto, photo_url: str) -> UserPhoto:
        photo.photo_url = photo_url
        await self.session.commit()
        await self.session.refresh(photo)
        return photo

    async def delete(self, photo: UserPhoto) -> None:
        await self.session.delete(photo)
        await self.session.commit()
