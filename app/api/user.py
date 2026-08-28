from fastapi import (
    Query,
    status,
    Depends,
    Request,
    APIRouter,
    HTTPException,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.user import UserRead, UserListItem, UserUpdate
from app.services.user import UserService
from app.schemas.pagination import PaginatedResponse
from app.core.limiter import limiter

router = APIRouter(tags=["users"])


@router.get(
    path="/users/list",
    response_model=PaginatedResponse[UserListItem],
    tags=["users"],
    summary="List of all users",
)
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100, description="Quantity per page"),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    return await service.get_all(page=page, page_size=page_size)


@router.patch(
    path="/users/{user_id}",
    response_model=UserRead,
    tags=["users"],
    summary="Update user information",
)
@limiter.limit("10/minute")
async def update_user(
    request: Request,
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    data = body.model_dump(exclude_none=True)
    user = await service.update(user_id=user_id, data=data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id={user_id} not found.",
        )
    return user


@router.get(
    path="/users/{user_id}",
    response_model=UserRead,
    tags=["users"],
    summary="Detailed user information",
)
@limiter.limit("30/minute")
async def get_user(request: Request, user_id: int, db: AsyncSession = Depends(get_db)):
    service = UserService(db)
    user = await service.get_by_id(user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id={user_id} not found.",
        )
    return user
