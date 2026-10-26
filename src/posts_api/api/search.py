"""Authenticated publication search."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.api.schemas.pagination import CursorPage
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.search import normalize_query, snippet

router = APIRouter(prefix="/search", tags=["search"])


class SegmentResponse(BaseModel):
    text: str
    highlighted: bool


class SearchPostResponse(BaseModel):
    id: UUID
    author_id: UUID = Field(serialization_alias="authorId")
    author_handle: str | None = Field(serialization_alias="authorHandle")
    created_at: datetime = Field(serialization_alias="createdAt")
    parent_id: UUID | None = Field(serialization_alias="parentId")
    snippet: list[SegmentResponse]


@router.get("/posts")
async def search_posts(
    q: Annotated[str, Query(min_length=3)],
    current_user: CurrentUserDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[SearchPostResponse]:
    query = normalize_query(q)
    decoded = Cursor.decode(cursor) if cursor is not None else None
    await FollowRepository(session).ensure_profile(current_user)
    results, next_cursor = await PostRepository(session).search(
        query, current_user.id, cursor=decoded
    )
    return CursorPage(
        items=[
            SearchPostResponse(
                id=post.id,
                author_id=post.author_id,
                author_handle=post.author_handle,
                created_at=post.created_at,
                parent_id=post.parent_id,
                snippet=[
                    SegmentResponse(text=part.text, highlighted=part.highlighted)
                    for part in snippet(post.content, query, positions)
                ],
            )
            for post, positions in results
        ],
        next_cursor=next_cursor,
    )
