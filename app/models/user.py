from datetime import datetime

from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(
        String(50), unique=True, index=True, nullable=True
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    phone_number: Mapped[str] = mapped_column(
        String(12), unique=True, index=True, nullable=False
    )
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    photos: Mapped[list["UserPhoto"]] = relationship(
        "UserPhoto", back_populates="user", cascade="all, delete-orphan"
    )


class UserPhoto(Base):
    __tablename__ = "user_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    photo_url: Mapped[str] = mapped_column(String(500))
    user: Mapped["User"] = relationship("User", back_populates="photos")
