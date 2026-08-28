import re

from pydantic import BaseModel, field_validator

from app.schemas.user import UserRead

PHONE_PATTERN = r"^\+?998[0-9]{9}$"


class PhoneNumberRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        if not re.match(PHONE_PATTERN, value):
            raise ValueError(
                "Telefon raqam noto'g'ri formatda. To'g'ri format: +998901234567 yoki 998901234567"
            )
        return value.lstrip("+")


class SendCodeResponse(BaseModel):
    sent: bool
    debug_code: str  # TODO: remove once a real SMS provider is wired up


class VerifyCodeRequest(PhoneNumberRequest):
    code: str


class VerifyCodeResponse(BaseModel):
    is_new_user: bool
    phone_number: str
    access_token: str | None = None
    user: UserRead | None = None


class CompleteProfileRequest(PhoneNumberRequest):
    first_name: str
    last_name: str


class AuthTokenResponse(BaseModel):
    access_token: str
    user: UserRead
