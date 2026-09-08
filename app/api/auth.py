from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.repositories.user_photo import UserPhotoRepository
from app.schemas.auth import (
    AuthTokenResponse,
    CompleteProfileRequest,
    PhoneNumberRequest,
    SendCodeResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.schemas.user import UserRead
from app.services.auth import AuthService
from app.utils.media import build_absolute_url

router = APIRouter(prefix="/auth", tags=["auth"])


async def _build_user_read(request: Request, db: AsyncSession, user) -> UserRead:
    last_photo = await UserPhotoRepository(db).get_last_by_user_id(user.id)
    user_data = UserRead.model_validate(user)
    user_data.photo_url = (
        build_absolute_url(request, last_photo.photo_url) if last_photo else None
    )
    return user_data


@router.post(
    "/send-code", response_model=SendCodeResponse, summary="Send SMS verification code"
)
@limiter.limit("5/minute")
async def send_code(
    request: Request, body: PhoneNumberRequest, db: AsyncSession = Depends(get_db)
):
    service = AuthService(db)
    code = await service.send_code(body.phone_number)
    return SendCodeResponse(sent=True, debug_code=code)


@router.post(
    "/verify-code", response_model=VerifyCodeResponse, summary="Verify SMS code"
)
@limiter.limit("10/minute")
async def verify_code(
    request: Request, body: VerifyCodeRequest, db: AsyncSession = Depends(get_db)
):
    service = AuthService(db)
    result = await service.verify_code(body.phone_number, body.code)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code.",
        )

    is_new_user, user, token = result
    return VerifyCodeResponse(
        is_new_user=is_new_user,
        phone_number=body.phone_number,
        access_token=token,
        user=await _build_user_read(request, db, user) if user else None,
    )


@router.post(
    "/complete-profile",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete registration for a new phone number",
)
@limiter.limit("5/minute")
async def complete_profile(
    request: Request, body: CompleteProfileRequest, db: AsyncSession = Depends(get_db)
):
    service = AuthService(db)
    result = await service.complete_profile(
        phone_number=body.phone_number,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is not verified or a user already exists for it.",
        )

    user, token = result
    return AuthTokenResponse(
        access_token=token, user=await _build_user_read(request, db, user)
    )


@router.get("/me", response_model=UserRead, summary="Get current authenticated user")
async def get_me(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _build_user_read(request, db, current_user)
