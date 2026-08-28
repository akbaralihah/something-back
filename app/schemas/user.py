import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict, field_validator


class UserRead(BaseModel):
    id: int
    first_name: str
    last_name: str
    username: Optional[str]
    email: Optional[EmailStr]
    phone_number: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "first_name": "Akbarali",
                "last_name": "Salohiddinov",
                "username": "akbarali_hah",
                "email": "akbarali4hah@gmail.com",
                "phone_number": "998200158060",
                "is_active": True,
                "is_superuser": False,
                "created_at": "2026-04-22T10:00:00",
                "updated_at": "2026-04-22T10:00:00",
            }
        },
    )


class UserListItem(BaseModel):
    id: int
    username: Optional[str]
    email: Optional[EmailStr]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        pattern = r"^\+?998[0-9]{9}$"
        if not re.match(pattern, value):
            raise ValueError(
                "Telefon raqam noto'g'ri formatda. To'g'ri format: +998901234567 yoki 998901234567"
            )
        return value.lstrip("+")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "akbarali_hah",
                "email": "akbarali4hah@gmail.com",
                "phone_number": "+998200158060",
            }
        }
    )
