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
