# Chat Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first, basic chat subsystem — private/group/channel chats with owner/member roles, message persistence, and a single-connection-per-user WebSocket for live messaging.

**Architecture:** Follows the existing layered pattern (`model → repository → service → api`) already used by the user module. New pieces: `Chat`/`ChatMember`/`Message` models, `ChatRepository`/`MessageRepository`, a `ChatService` that centralizes membership/role rules and returns typed `ChatError` values instead of raising, a REST router for chat/message CRUD+history, and a small `app/ws/` package (`ConnectionManager` + the `/ws/chat` endpoint) that reuses `ChatService` to persist and fan out messages.

**Tech Stack:** FastAPI 0.136.0, SQLAlchemy 2.0 (async, `Mapped`/`mapped_column`), asyncpg, Alembic, Pydantic v2, existing JWT (`python-jose`) bearer auth.

**Spec:** [docs/superpowers/specs/2026-09-08-chat-module-design.md](../specs/2026-09-08-chat-module-design.md)

## Global Constraints

- No new test framework — the project has no `tests/` dir and no pytest dependency; every existing module is verified manually, and this module follows the same convention (per spec's Testing section). Each task below is verified with a small ad-hoc script or HTTP/WebSocket call, not a pytest suite.
- Follow existing conventions exactly: async SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`), naming convention already defined in `app/db/base.py` (don't invent custom constraint names), repositories take a raw `AsyncSession` in `__init__`, services take a raw `AsyncSession` and construct their own repositories, routers use `@limiter.limit(...)` on every endpoint like `app/api/user.py` does.
- WebSocket connection registry is in-process memory only (no Redis fanout) — this is a known, accepted limitation, not a bug to fix in this plan.
- Sending a chat message happens only over WebSocket in this iteration — do not add a REST "send message" endpoint.
- `DATABASE_URL` in `.env` already points at a reachable local Postgres (`something_db`) — migrations in this plan run against it directly.

---

## Task 1: Chat data model + migration

**Files:**
- Create: `app/models/chat.py`
- Modify: `migrations/env.py` (add the new model imports so autogenerate sees them)

**Interfaces:**
- Produces: `ChatType` (str enum: `PRIVATE="private"`, `GROUP="group"`, `CHANNEL="channel"`), `ChatRole` (str enum: `OWNER="owner"`, `MEMBER="member"`), `Chat`, `ChatMember`, `Message` — all later tasks import these from `app.models.chat`.

- [ ] **Step 1: Write the models**

```python
# app/models/chat.py
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatType(str, enum.Enum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"


class ChatRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[ChatType] = mapped_column(SAEnum(ChatType, name="chat_type"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (UniqueConstraint("chat_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(SAEnum(ChatRole, name="chat_role"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 2: Register the models with Alembic**

In `migrations/env.py`, add alongside the existing model imports (right after
`from app.models.phone_verification import PhoneVerification`):

```python
from app.models.chat import Chat, ChatMember, Message
```

- [ ] **Step 3: Generate the migration**

Run: `.venv/bin/alembic revision --autogenerate -m "add chats, chat_members, messages"`

Expected: a new file appears under `migrations/versions/`. Open it and confirm
it contains `op.create_table('chats', ...)`, `op.create_table('chat_members', ...)`
(with a unique constraint on `chat_id`+`user_id`), and `op.create_table('messages', ...)`,
each using `op.f(...)` names consistent with the other migrations in that
directory. Adjust only if autogenerate produced something unexpected (e.g.
missing FK `ondelete`) — compare against `migrations/versions/3531e13daad7_create_users_and_user_photos.py`
for the expected shape.

- [ ] **Step 4: Apply the migration**

Run: `.venv/bin/alembic upgrade head`

Expected: command exits 0 with `Running upgrade ... -> <new_revision>, add chats, chat_members, messages`.

- [ ] **Step 5: Verify the tables exist**

Run:

```bash
.venv/bin/python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text(
            \"SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('chats','chat_members','messages') ORDER BY tablename\"
        ))
        print(result.scalars().all())

asyncio.run(main())
"
```

Expected: `['chat_members', 'chats', 'messages']`.

- [ ] **Step 6: Commit**

```bash
git add app/models/chat.py migrations/env.py migrations/versions/
git commit -m "$(cat <<'EOF'
feat: add Chat, ChatMember, Message models and migration

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Chat and message repositories

**Files:**
- Create: `app/repositories/chat.py`
- Create: `app/repositories/message.py`

**Interfaces:**
- Consumes: `Chat`, `ChatMember`, `ChatType`, `ChatRole`, `Message` from `app.models.chat` (Task 1).
- Produces:
  - `ChatRepository(session)` with `get_by_id(chat_id) -> Chat | None`, `get_private_between(user_a, user_b) -> Chat | None`, `create(type_, title, creator_id, member_ids) -> Chat`, `get_membership(chat_id, user_id) -> ChatMember | None`, `list_members(chat_id) -> list[ChatMember]`, `list_for_user(user_id, page, page_size) -> tuple[list[Chat], int]`.
  - `MessageRepository(session)` with `create(chat_id, sender_id, text) -> Message`, `list_for_chat(chat_id, page, page_size) -> tuple[list[Message], int]`.
  - Later tasks (Task 4 `ChatService`) call these methods with exactly these names/signatures.

- [ ] **Step 1: Write the chat repository**

```python
# app/repositories/chat.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.chat import Chat, ChatMember, ChatRole, ChatType


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, chat_id: int) -> Chat | None:
        result = await self.session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    async def get_private_between(self, user_a: int, user_b: int) -> Chat | None:
        cm1 = aliased(ChatMember)
        cm2 = aliased(ChatMember)
        result = await self.session.execute(
            select(Chat)
            .join(cm1, cm1.chat_id == Chat.id)
            .join(cm2, cm2.chat_id == Chat.id)
            .where(
                Chat.type == ChatType.PRIVATE,
                cm1.user_id == user_a,
                cm2.user_id == user_b,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, type_: ChatType, title: str | None, creator_id: int, member_ids: list[int]
    ) -> Chat:
        chat = Chat(type=type_, title=title, created_by=creator_id)
        self.session.add(chat)
        await self.session.flush()

        members = [ChatMember(chat_id=chat.id, user_id=creator_id, role=ChatRole.OWNER)]
        members += [
            ChatMember(chat_id=chat.id, user_id=user_id, role=ChatRole.MEMBER)
            for user_id in member_ids
        ]
        self.session.add_all(members)
        await self.session.commit()
        await self.session.refresh(chat)
        return chat

    async def get_membership(self, chat_id: int, user_id: int) -> ChatMember | None:
        result = await self.session.execute(
            select(ChatMember).where(
                ChatMember.chat_id == chat_id, ChatMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, chat_id: int) -> list[ChatMember]:
        result = await self.session.execute(
            select(ChatMember).where(ChatMember.chat_id == chat_id)
        )
        return list(result.scalars().all())

    async def list_for_user(
        self, user_id: int, page: int, page_size: int
    ) -> tuple[list[Chat], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            select(func.count())
            .select_from(ChatMember)
            .where(ChatMember.user_id == user_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Chat)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .where(ChatMember.user_id == user_id)
            .order_by(Chat.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total
```

- [ ] **Step 2: Write the message repository**

```python
# app/repositories/message.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, chat_id: int, sender_id: int, text: str) -> Message:
        message = Message(chat_id=chat_id, sender_id=sender_id, text=text)
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def list_for_chat(
        self, chat_id: int, page: int, page_size: int
    ) -> tuple[list[Message], int]:
        offset = (page - 1) * page_size

        count_result = await self.session.execute(
            select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total
```

- [ ] **Step 3: Verify against the real DB**

Run:

```bash
.venv/bin/python -c "
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.chat import ChatType
from app.repositories.chat import ChatRepository
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository

async def main():
    async with AsyncSessionLocal() as db:
        user_repo = UserRepository(db)
        u1 = await user_repo.create_from_phone('998900000001', 'Alice', 'Test')
        u2 = await user_repo.create_from_phone('998900000002', 'Bob', 'Test')

        chat_repo = ChatRepository(db)
        chat = await chat_repo.create(ChatType.PRIVATE, None, u1.id, [u2.id])
        print('chat id', chat.id, chat.type)

        same = await chat_repo.get_private_between(u1.id, u2.id)
        print('lookup matches:', same.id == chat.id)

        members = await chat_repo.list_members(chat.id)
        print('members:', sorted((m.user_id, m.role.value) for m in members))

        msg_repo = MessageRepository(db)
        msg = await msg_repo.create(chat.id, u1.id, 'hello bob')
        print('message id', msg.id, msg.text)

        chats, total = await chat_repo.list_for_user(u2.id, page=1, page_size=10)
        print('bob chats total:', total, [c.id for c in chats])

asyncio.run(main())
"
```

Expected output shows the chat id, `ChatType.PRIVATE`, `lookup matches: True`,
members `[(u1.id, 'owner'), (u2.id, 'member')]`, the created message id/text,
and `bob chats total: 1` including the chat id.

- [ ] **Step 4: Commit**

```bash
git add app/repositories/chat.py app/repositories/message.py
git commit -m "$(cat <<'EOF'
feat: add ChatRepository and MessageRepository

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Chat schemas

**Files:**
- Create: `app/schemas/chat.py`

**Interfaces:**
- Consumes: `ChatType`, `ChatRole` from `app.models.chat` (Task 1).
- Produces: `ChatCreate`, `ChatMemberRead`, `ChatRead`, `ChatDetail`, `MessageRead` — consumed by `app/api/chat.py` (Task 5) and `app/ws/chat.py` (Task 6).

- [ ] **Step 1: Write the schemas**

```python
# app/schemas/chat.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.chat import ChatRole, ChatType


class ChatCreate(BaseModel):
    type: ChatType
    title: str | None = None
    member_ids: list[int]

    @model_validator(mode="after")
    def validate_by_type(self) -> "ChatCreate":
        if self.type == ChatType.PRIVATE:
            if len(self.member_ids) != 1:
                raise ValueError(
                    "Private chat requires exactly one other member_id."
                )
        else:
            if not self.title or not self.title.strip():
                raise ValueError("title is required for group and channel chats.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "group",
                "title": "Weekend plans",
                "member_ids": [2, 3],
            }
        }
    )


class ChatMemberRead(BaseModel):
    user_id: int
    role: ChatRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRead(BaseModel):
    id: int
    type: ChatType
    title: str | None
    created_by: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatDetail(ChatRead):
    members: list[ChatMemberRead]


class MessageRead(BaseModel):
    id: int
    chat_id: int
    sender_id: int
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Verify validation rules**

Run:

```bash
.venv/bin/python -c "
from pydantic import ValidationError
from app.schemas.chat import ChatCreate

ChatCreate(type='private', member_ids=[2])
print('private ok')

try:
    ChatCreate(type='private', member_ids=[2, 3])
    print('BUG: should have failed')
except ValidationError:
    print('private with 2 members correctly rejected')

try:
    ChatCreate(type='group', member_ids=[2, 3])
    print('BUG: should have failed')
except ValidationError:
    print('group without title correctly rejected')

ChatCreate(type='group', title='Team', member_ids=[2, 3])
print('group ok')
"
```

Expected: `private ok`, `private with 2 members correctly rejected`,
`group without title correctly rejected`, `group ok`.

- [ ] **Step 3: Commit**

```bash
git add app/schemas/chat.py
git commit -m "$(cat <<'EOF'
feat: add chat Pydantic schemas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ChatService

**Files:**
- Create: `app/services/chat.py`

**Interfaces:**
- Consumes: `ChatRepository`, `MessageRepository` (Task 2), `UserRepository` (existing, `app/repositories/user.py`, method `get_by_id(user_id) -> User | None`), `ChatType`, `ChatRole`, `Chat`, `Message` (Task 1).
- Produces: `ChatError` enum with a `.detail` property, and `ChatService(db)` with:
  - `create_chat(creator_id, type_, title, member_ids) -> tuple[Chat, bool] | ChatError` (bool = was newly created)
  - `get_chat_detail(chat_id, user_id) -> tuple[Chat, list[ChatMember]] | ChatError`
  - `list_user_chats(user_id, page, page_size) -> dict` (shape matches `PaginatedResponse`)
  - `list_messages(chat_id, user_id, page, page_size) -> dict | ChatError`
  - `send_message(sender_id, chat_id, text) -> tuple[Message, list[int]] | ChatError` (`list[int]` = member user ids to notify)
  - These exact names/signatures are what `app/api/chat.py` (Task 5) and `app/ws/chat.py` (Task 6) call.

- [ ] **Step 1: Write the service**

```python
# app/services/chat.py
import enum
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, ChatMember, ChatRole, ChatType, Message
from app.repositories.chat import ChatRepository
from app.repositories.message import MessageRepository
from app.repositories.user import UserRepository


class ChatError(str, enum.Enum):
    NOT_FOUND = "not_found"
    NOT_A_MEMBER = "not_a_member"
    CHANNEL_WRITE_FORBIDDEN = "channel_write_forbidden"
    INVALID_MEMBER = "invalid_member"

    @property
    def detail(self) -> str:
        return {
            ChatError.NOT_FOUND: "Chat not found.",
            ChatError.NOT_A_MEMBER: "You are not a member of this chat.",
            ChatError.CHANNEL_WRITE_FORBIDDEN: "Only the channel owner can send messages.",
            ChatError.INVALID_MEMBER: (
                "member_ids must reference existing users other than yourself."
            ),
        }[self]


def _paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size),
    }


class ChatService:
    def __init__(self, db: AsyncSession):
        self.chat_repo = ChatRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)

    async def create_chat(
        self, creator_id: int, type_: ChatType, title: str | None, member_ids: list[int]
    ) -> tuple[Chat, bool] | ChatError:
        for user_id in member_ids:
            if user_id == creator_id:
                return ChatError.INVALID_MEMBER
            if await self.user_repo.get_by_id(user_id) is None:
                return ChatError.INVALID_MEMBER

        if type_ == ChatType.PRIVATE:
            other_id = member_ids[0]
            existing = await self.chat_repo.get_private_between(creator_id, other_id)
            if existing is not None:
                return existing, False
            chat = await self.chat_repo.create(type_, None, creator_id, [other_id])
            return chat, True

        chat = await self.chat_repo.create(type_, title, creator_id, member_ids)
        return chat, True

    async def get_chat_detail(
        self, chat_id: int, user_id: int
    ) -> tuple[Chat, list[ChatMember]] | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND
        if await self.chat_repo.get_membership(chat_id, user_id) is None:
            return ChatError.NOT_A_MEMBER
        members = await self.chat_repo.list_members(chat_id)
        return chat, members

    async def list_user_chats(self, user_id: int, page: int, page_size: int) -> dict:
        chats, total = await self.chat_repo.list_for_user(user_id, page, page_size)
        return _paginate(chats, total, page, page_size)

    async def list_messages(
        self, chat_id: int, user_id: int, page: int, page_size: int
    ) -> dict | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND
        if await self.chat_repo.get_membership(chat_id, user_id) is None:
            return ChatError.NOT_A_MEMBER
        messages, total = await self.message_repo.list_for_chat(chat_id, page, page_size)
        return _paginate(messages, total, page, page_size)

    async def send_message(
        self, sender_id: int, chat_id: int, text: str
    ) -> tuple[Message, list[int]] | ChatError:
        chat = await self.chat_repo.get_by_id(chat_id)
        if chat is None:
            return ChatError.NOT_FOUND

        membership = await self.chat_repo.get_membership(chat_id, sender_id)
        if membership is None:
            return ChatError.NOT_A_MEMBER

        if chat.type == ChatType.CHANNEL and membership.role != ChatRole.OWNER:
            return ChatError.CHANNEL_WRITE_FORBIDDEN

        message = await self.message_repo.create(chat_id, sender_id, text)
        members = await self.chat_repo.list_members(chat_id)
        return message, [member.user_id for member in members]
```

- [ ] **Step 2: Verify the role rule and error paths**

Run (creates a channel, confirms only the owner can post, confirms a
non-member is rejected):

```bash
.venv/bin/python -c "
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.chat import ChatType
from app.repositories.user import UserRepository
from app.services.chat import ChatError, ChatService

async def main():
    async with AsyncSessionLocal() as db:
        user_repo = UserRepository(db)
        owner = await user_repo.create_from_phone('998900000003', 'Chan', 'Owner')
        member = await user_repo.create_from_phone('998900000004', 'Chan', 'Member')
        outsider = await user_repo.create_from_phone('998900000005', 'Out', 'Sider')

        service = ChatService(db)
        result = await service.create_chat(owner.id, ChatType.CHANNEL, 'News', [member.id])
        chat, created = result
        print('channel created:', created, chat.id)

        owner_send = await service.send_message(owner.id, chat.id, 'hello all')
        print('owner send ok:', not isinstance(owner_send, ChatError))

        member_send = await service.send_message(member.id, chat.id, 'can I post?')
        print('member send blocked:', member_send == ChatError.CHANNEL_WRITE_FORBIDDEN)

        outsider_send = await service.send_message(outsider.id, chat.id, 'hi')
        print('outsider send blocked:', outsider_send == ChatError.NOT_A_MEMBER)

asyncio.run(main())
"
```

Expected: `channel created: True <id>`, `owner send ok: True`,
`member send blocked: True`, `outsider send blocked: True`.

- [ ] **Step 3: Commit**

```bash
git add app/services/chat.py
git commit -m "$(cat <<'EOF'
feat: add ChatService with membership and channel-role rules

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: REST API for chats

**Files:**
- Create: `app/api/chat.py`
- Modify: `main.py` (register the router)

**Interfaces:**
- Consumes: `ChatService`, `ChatError` (Task 4); `ChatCreate`, `ChatRead`, `ChatDetail`, `ChatMemberRead`, `MessageRead` (Task 3); `get_current_user`, `get_db` (existing, `app/api/deps.py` / `app/db/session.py`); `PaginatedResponse` (existing, `app/schemas/pagination.py`); `limiter` (existing, `app/core/limiter.py`).
- Produces: `router` (APIRouter, prefix `/chats`) — imported into `main.py`.

- [ ] **Step 1: Write the router**

```python
# app/api/chat.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatCreate, ChatDetail, ChatMemberRead, ChatRead, MessageRead
from app.schemas.pagination import PaginatedResponse
from app.services.chat import ChatError, ChatService

router = APIRouter(prefix="/chats", tags=["chats"])

_ERROR_STATUS = {
    ChatError.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ChatError.NOT_A_MEMBER: status.HTTP_403_FORBIDDEN,
    ChatError.CHANNEL_WRITE_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ChatError.INVALID_MEMBER: status.HTTP_400_BAD_REQUEST,
}


def _raise_for_error(error: ChatError) -> None:
    raise HTTPException(status_code=_ERROR_STATUS[error], detail=error.detail)


@router.post("", response_model=ChatRead, summary="Create or get a chat")
@limiter.limit("20/minute")
async def create_chat(
    request: Request,
    response: Response,
    body: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.create_chat(
        creator_id=current_user.id,
        type_=body.type,
        title=body.title,
        member_ids=body.member_ids,
    )
    if isinstance(result, ChatError):
        _raise_for_error(result)

    chat, created = result
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return chat


@router.get("", response_model=PaginatedResponse[ChatRead], summary="List of my chats")
@limiter.limit("30/minute")
async def list_chats(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100, description="Quantity per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    return await service.list_user_chats(
        user_id=current_user.id, page=page, page_size=page_size
    )


@router.get("/{chat_id}", response_model=ChatDetail, summary="Chat details and members")
@limiter.limit("30/minute")
async def get_chat(
    request: Request,
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.get_chat_detail(chat_id=chat_id, user_id=current_user.id)
    if isinstance(result, ChatError):
        _raise_for_error(result)

    chat, members = result
    return ChatDetail(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        created_by=chat.created_by,
        created_at=chat.created_at,
        members=[ChatMemberRead.model_validate(member) for member in members],
    )


@router.get(
    "/{chat_id}/messages",
    response_model=PaginatedResponse[MessageRead],
    summary="Chat message history",
)
@limiter.limit("30/minute")
async def list_messages(
    request: Request,
    chat_id: int,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Quantity per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ChatService(db)
    result = await service.list_messages(
        chat_id=chat_id, user_id=current_user.id, page=page, page_size=page_size
    )
    if isinstance(result, ChatError):
        _raise_for_error(result)
    return result
```

- [ ] **Step 2: Register the router in main.py**

In `main.py`, add the import alongside the other routers:

```python
from app.api.chat import router as chat_router
```

And register it alongside the others near the bottom of the file:

```python
app.include_router(chat_router)
```

(Leave this next to `app.include_router(user_photo_router)` — don't reorder
the existing ones.)

- [ ] **Step 3: Start the server and verify over HTTP**

Run: `.venv/bin/uvicorn main:app --reload` (in one terminal), then in another:

```bash
# get a token for an existing test user (reuse one created in Task 2/4's verification,
# or register a fresh one through /auth/send-code + /auth/verify-code + /auth/complete-profile)
TOKEN="<paste an access_token here>"
OTHER_USER_ID=<an existing user's id, not the token's owner>

curl -s -X POST localhost:8000/chats \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"type\": \"private\", \"member_ids\": [$OTHER_USER_ID]}" | python -m json.tool

curl -s localhost:8000/chats -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Expected: first call returns `201` with a `ChatRead` JSON body (`type: "private"`);
repeating the same POST returns `200` with the same `id` (get-or-create); the
`GET /chats` call lists that chat.

- [ ] **Step 4: Commit**

```bash
git add app/api/chat.py main.py
git commit -m "$(cat <<'EOF'
feat: add REST endpoints for creating/listing chats and history

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: WebSocket connection manager and `/ws/chat` endpoint

**Files:**
- Create: `app/ws/__init__.py` (empty)
- Create: `app/ws/manager.py`
- Create: `app/ws/chat.py`
- Modify: `main.py` (remove the placeholder `/ws` echo endpoint, register the new WebSocket router)

**Interfaces:**
- Consumes: `ChatService`, `ChatError` (Task 4); `MessageRead` (Task 3); `decode_access_token` (existing, `app/utils/jwt.py`); `UserRepository` (existing, `app/repositories/user.py`); `get_db` (existing, `app/db/session.py`).
- Produces: `manager` (module-level `ConnectionManager` singleton in `app/ws/manager.py`); `router` (APIRouter exposing `GET /ws/chat`) in `app/ws/chat.py` — imported into `main.py`.

- [ ] **Step 1: Write the connection manager**

```python
# app/ws/manager.py
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}

    def connect(self, user_id: int, websocket: WebSocket) -> None:
        self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(user_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            del self._connections[user_id]

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        for websocket in list(self._connections.get(user_id, ())):
            await websocket.send_json(payload)


manager = ConnectionManager()
```

- [ ] **Step 2: Write the WebSocket endpoint**

```python
# app/ws/chat.py
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.user import UserRepository
from app.schemas.chat import MessageRead
from app.services.chat import ChatError, ChatService
from app.utils.jwt import decode_access_token
from app.ws.manager import manager

router = APIRouter()


async def _handle_incoming(
    service: ChatService, user_id: int, data: dict, websocket: WebSocket
) -> None:
    if not isinstance(data, dict) or data.get("action") != "send_message":
        await websocket.send_json({"type": "error", "detail": "Unknown action."})
        return

    chat_id = data.get("chat_id")
    text = data.get("text")
    if not isinstance(chat_id, int) or not isinstance(text, str) or not text.strip():
        await websocket.send_json(
            {"type": "error", "detail": "chat_id and text are required."}
        )
        return

    result = await service.send_message(sender_id=user_id, chat_id=chat_id, text=text)
    if isinstance(result, ChatError):
        await websocket.send_json({"type": "error", "detail": result.detail})
        return

    message, member_ids = result
    payload = {
        "type": "message",
        "data": MessageRead.model_validate(message).model_dump(mode="json"),
    }
    for member_id in member_ids:
        await manager.send_to_user(member_id, payload)


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = decode_access_token(token)
    user = await UserRepository(db).get_by_id(user_id) if user_id is not None else None
    if user is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await websocket.accept()
    manager.connect(user.id, websocket)
    service = ChatService(db)

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON payload."}
                )
                continue

            await _handle_incoming(service, user.id, data, websocket)
    finally:
        manager.disconnect(user.id, websocket)
```

- [ ] **Step 3: Wire it into main.py, remove the placeholder `/ws`**

In `main.py`, remove this entire block:

```python
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    try:
        while True:
            data = await ws.receive_json()
            data["username"] = str(data["username"]).capitalize()
            await ws.send_json(data)
    except WebSocketDisconnect:
        print("Client disconnected")
```

Remove `WebSocket, WebSocketDisconnect` from the `fastapi` import at the top of
`main.py` if nothing else in the file uses them after the removal.

Add the import:

```python
from app.ws.chat import router as chat_ws_router
```

And register it next to the other `include_router` calls:

```python
app.include_router(chat_ws_router)
```

- [ ] **Step 4: Verify live delivery end-to-end**

With the server running (`.venv/bin/uvicorn main:app --reload`), run this
script with two real access tokens for two members of the same chat (reuse
the private chat created in Task 5's verification):

```bash
.venv/bin/python -c "
import asyncio
import json
import websockets

TOKEN_A = '<user A token>'
TOKEN_B = '<user B token>'
CHAT_ID = <chat id from Task 5>

async def listener(token, label, received):
    async with websockets.connect(f'ws://localhost:8000/ws/chat?token={token}') as ws:
        received.append('connected')
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        print(label, 'received:', msg)

async def sender(token):
    await asyncio.sleep(1)
    async with websockets.connect(f'ws://localhost:8000/ws/chat?token={token}') as ws:
        await ws.send(json.dumps({'action': 'send_message', 'chat_id': CHAT_ID, 'text': 'hi from A'}))
        await asyncio.sleep(1)

async def main():
    received = []
    await asyncio.gather(listener(TOKEN_B, 'B', received), sender(TOKEN_A))

asyncio.run(main())
"
```

Expected: prints `B received: {"type": "message", "data": {... "text": "hi from A" ...}}`.
Then confirm persistence:

```bash
curl -s "localhost:8000/chats/<chat id>/messages" -H "Authorization: Bearer <token A or B>" | python -m json.tool
```

Expected: the message appears in the paginated history.

Also verify the channel-role rejection over the socket: connect as the
non-owner member of the channel chat from Task 4's verification and send a
`send_message` frame for that chat — expect
`{"type": "error", "detail": "Only the channel owner can send messages."}`
back on the same connection, with the connection remaining open.

- [ ] **Step 5: Commit**

```bash
git add app/ws/ main.py
git commit -m "$(cat <<'EOF'
feat: add /ws/chat endpoint with per-user connection manager

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Full end-to-end pass

**Files:** none (verification-only task; no code changes expected).

**Interfaces:** none — exercises everything from Tasks 1–6 through the public HTTP/WebSocket surface only.

- [ ] **Step 1: Fresh-eyes walkthrough**

With the server running against the migrated DB, using two freshly
registered users (via `/auth/send-code` → `/auth/verify-code` →
`/auth/complete-profile`, same as any other client would):

1. Create a private chat between them (`POST /chats`) — confirm `201`, then
   repeat the same call and confirm `200` with the same `id`.
2. Create a group chat with both as members (`POST /chats`, `type: "group"`,
   a `title`) — confirm `201` and that `GET /chats/{id}` lists both members
   with the creator as `owner`.
3. Create a channel the same way — confirm the non-owner member's
   `send_message` over `/ws/chat` is rejected with `CHANNEL_WRITE_FORBIDDEN`'s
   detail text, while the owner's message goes through and is delivered live
   to the other member's open connection.
4. In the group chat, send a message from user A while user B's socket is
   *not* connected — confirm user B does not receive a live frame, but the
   message shows up when B calls `GET /chats/{id}/messages` afterward.
5. Confirm `GET /chats/{id}` and `GET /chats/{id}/messages` both return `403`
   for a third user who isn't a member, and `404` for a non-existent
   `chat_id`.

- [ ] **Step 2: Note the outcome**

If every check in Step 1 behaves as described, the chat module is complete
for this iteration. If anything deviates, fix it in the relevant task's file
and re-run that task's verification before re-running this end-to-end pass.
