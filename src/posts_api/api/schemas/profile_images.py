"""What uploading a profile photo or cover answers: only its URL, for the screen to swap in."""

from pydantic import BaseModel, Field


class AvatarSummary(BaseModel):
    avatar_url: str = Field(serialization_alias="avatarUrl")


class CoverSummary(BaseModel):
    cover_url: str = Field(serialization_alias="coverUrl")
