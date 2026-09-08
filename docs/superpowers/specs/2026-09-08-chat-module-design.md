# Chat module — design spec

Date: 2026-09-08

## Purpose

Add a first, basic chat subsystem to the backend, modeled loosely on
Telegram: private / group / channel chats, membership with a minimal
role model, and a WebSocket-based live messaging channel. This is the
first of possibly several chat-related iterations — scope here is
deliberately minimal (YAGNI): no read receipts, typing indicators,
attachments, message editing/deletion, or multi-process fanout.

## Architecture

Follows the existing layered pattern in the repo
(`model → repository → service → api`), the same one used by
`app/models/user.py`, `app/repositories/user.py`, `app/services/user.py`,
`app/api/user.py`. New pieces:

- `app/models/chat.py` — SQLAlchemy models: `Chat`, `ChatMember`, `Message`.
- `app/schemas/chat.py` — Pydantic schemas for REST + WebSocket payloads.
- `app/repositories/chat.py` — DB access for chats/members/messages.
- `app/services/chat.py` — business rules (get-or-create private chat,
  membership checks, channel-owner-only send rule, broadcasting).
- `app/api/chat.py` — REST endpoints (create/list/detail/history).
- `app/ws/manager.py` — in-memory `ConnectionManager` (per-user WebSocket
  registry).
- `app/ws/chat.py` — the `/ws/chat` WebSocket endpoint.
- `app/api/deps.py` — add a WebSocket-flavored auth dependency
  (token read from query param, reusing `decode_access_token`).
- `main.py` — remove the placeholder echo `/ws` endpoint, include the new
  chat REST router and the chat WebSocket route.
- Alembic migration for the three new tables.

## Data model

```
Chat
  id: int, PK
  type: enum("private", "group", "channel")
  title: str | None        # required for group/channel, always null for private
  created_by: FK users.id
  created_at: datetime

ChatMember
  id: int, PK
  chat_id: FK chats.id (CASCADE)
  user_id: FK users.id (CASCADE)
  role: enum("owner", "member")
  joined_at: datetime
  # unique constraint on (chat_id, user_id)

Message
  id: int, PK
  chat_id: FK chats.id (CASCADE)
  sender_id: FK users.id
  text: str
  created_at: datetime
```

Rules:
- **Private chats are get-or-create.** Creating a `private` chat between
  two users who already have one returns the existing chat instead of a
  duplicate — matches Telegram behavior and keeps the 1:1 relationship
  clean.
- **Roles**: the chat creator becomes `owner`; everyone else added at
  creation time is `member`. No further role management (promote/demote,
  kick) in this iteration.
- **Who can post**: in `private` and `group` chats, any member can send
  messages. In `channel` chats, only members with role `owner` can send;
  others can only receive.

## REST API

All endpoints sit behind the existing `HTTPBearer` + `get_current_user`
dependency, same as `app/api/user.py`.

- `POST /chats` — create a chat.
  Body: `{ type, title?, member_ids: [int] }`.
  For `type == "private"`, `member_ids` must contain exactly one other
  user id; if a private chat with that pair already exists, it is
  returned as-is (200-style get-or-create, not a duplicate 201).
  For `group`/`channel`, `title` is required.
- `GET /chats` — paginated list of the current user's chats
  (`PaginatedResponse`, same shape as `GET /users/list`).
- `GET /chats/{chat_id}` — chat details + member list.
  404 if the chat doesn't exist, 403 if the caller isn't a member.
- `GET /chats/{chat_id}/messages` — paginated message history, newest
  page first. Same 404/403 rules as above.

No REST endpoint to send a message — sending only happens over the
WebSocket, per the scope of this iteration.

## WebSocket API

One global connection per user (not per chat), mirroring how Telegram
multiplexes all chat traffic over a single connection.

- **Endpoint**: `GET /ws/chat?token=<jwt>`.
  Browsers can't set custom headers on a WebSocket handshake, so the JWT
  travels as a query parameter and is decoded with the existing
  `decode_access_token`. On missing/invalid/expired token: accept then
  immediately `close(code=4401)` — calling `close()` before `accept()`
  makes Starlette reject the handshake with a bare HTTP 403 instead of a
  WebSocket close frame, so accepting first is required to actually hand
  the client a `4401` close code.
- **Client → server** frame: `{"action": "send_message", "chat_id": int, "text": str}`.
- **Server → client** frames:
  - `{"type": "message", "data": <MessageRead>}`
  - `{"type": "error", "detail": str}`
- **Connection registry**: `ConnectionManager` holds
  `dict[user_id, set[WebSocket]]` in process memory, so a user can have
  multiple live connections (tabs/devices). On `send_message`:
  1. Service verifies the sender is a member of `chat_id` (403-equivalent
     `error` frame if not, connection stays open).
  2. If the chat is a `channel` and the sender's role isn't `owner`,
     reply with an `error` frame and drop the message.
  3. Otherwise persist the `Message`, then look up all `ChatMember`
     user ids for that chat and push the `message` frame to every one of
     them that currently has an open connection. Offline members simply
     pick the message up later via `GET /chats/{id}/messages`.

**Known limitation (accepted for this iteration):** the connection
registry lives in a single process's memory. If the backend ever runs as
multiple workers/instances, a message sent to a user connected to a
different process won't reach them live (though it's still persisted and
recoverable via REST history). Fixing this would mean introducing Redis
pub/sub (the project already depends on `redis` for rate limiting) to
fan out across processes — explicitly out of scope here, left as future
work.

The existing placeholder `@app.websocket("/ws")` echo handler in
[main.py](../../../main.py) is removed and replaced by the router that
exposes `/ws/chat`.

## Error handling

- WebSocket: bad/expired token → close 4401. Malformed JSON or unknown
  `action` → `error` frame, connection stays open. Chat not found / not a
  member / channel-write-without-owner-role → `error` frame, connection
  stays open.
- REST: 404 when the chat doesn't exist, 403 when the caller isn't a
  member — consistent with the 404 pattern already used in
  `app/api/user.py`.

## Testing

The project currently has no automated test suite (no `tests/` dir, no
pytest dependency) — every existing module is verified manually, so this
module follows the same convention rather than introducing new test
infrastructure as a side effect.

Manual verification plan:
1. Start the server, create two users through the existing phone+SMS
   auth flow.
2. Create a private chat between them via `POST /chats`; confirm a
   second identical `POST /chats` returns the same chat (get-or-create).
3. Create a group and a channel, add both users; confirm the channel
   rejects a `send_message` from the non-owner member with an `error`
   frame.
4. Connect two WebSocket clients (small Python script using the
   `websockets` package already in `pyproject.toml`) authenticated as
   each user, send a message from one, confirm the other receives it
   live and that `GET /chats/{id}/messages` shows it afterwards.
5. Disconnect one client, send a message to that user, confirm it's
   absent from live delivery but present in the REST history once they
   "come back" (i.e., just re-fetch history — no reconnect-replay
   mechanism in this iteration).
