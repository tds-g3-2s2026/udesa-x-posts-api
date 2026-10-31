"""Read followed activity with a single order, visibility and mute check before paging."""

import uuid

from sqlalchemy import String, literal, not_, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from posts_api.app.feed_pagination import FeedCursor
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.app.repositories.likes import liked_by
from posts_api.app.repositories.mutes import muted_by_viewer
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.app.repositories.retweets import retweeted_by
from posts_api.infrastructure.database.models import (
    FollowModel,
    PostModel,
    RetweetModel,
    UserProfileModel,
)


class FeedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_viewer(
        self,
        viewer_id: uuid.UUID,
        *,
        cursor: FeedCursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PostWithAuthor], str | None]:
        sharer = aliased(UserProfileModel)
        originals = (
            select(
                PostModel.id.label("post_id"),
                PostModel.created_at.label("activity_at"),
                literal(0).label("kind"),
                PostModel.author_id.label("actor_id"),
                literal(None, type_=String).label("shared_by"),
            )
            .join(FollowModel, FollowModel.followee_id == PostModel.author_id)
            .where(FollowModel.follower_id == viewer_id, PostModel.parent_id.is_(None))
        )
        shares = (
            select(
                RetweetModel.post_id,
                RetweetModel.created_at,
                literal(1),
                RetweetModel.user_id,
                sharer.handle,
            )
            .join(FollowModel, FollowModel.followee_id == RetweetModel.user_id)
            .join(sharer, sharer.id == RetweetModel.user_id)
            .where(
                FollowModel.follower_id == viewer_id,
                visible_to(
                    viewer_id,
                    author_id=sharer.id,
                    author_visibility=sharer.visibility,
                    author_deleted_at=sharer.deleted_at,
                ),
                # A retweet by a muted account leaves, whatever it shares.
                not_(muted_by_viewer(viewer_id, RetweetModel.user_id)),
            )
        )
        activity = union_all(originals, shares).subquery()
        position = (
            activity.c.activity_at,
            activity.c.post_id,
            activity.c.kind,
            activity.c.actor_id,
        )
        statement = (
            select(
                PostModel,
                UserProfileModel.handle,
                UserProfileModel.deleted_at,
                activity.c.activity_at,
                activity.c.kind,
                activity.c.actor_id,
                activity.c.shared_by,
                liked_by(viewer_id),
                retweeted_by(viewer_id),
            )
            .join(activity, activity.c.post_id == PostModel.id)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.deleted_at.is_(None),
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                    author_deleted_at=UserProfileModel.deleted_at,
                    # A reply of a closed account that somebody retweeted stays.
                    keeps_deleted_author=PostModel.parent_id.is_not(None),
                ),
                # A muted author leaves too when somebody else retweets them.
                not_(muted_by_viewer(viewer_id, PostModel.author_id)),
            )
        )
        if cursor is not None:
            statement = statement.where(
                tuple_(*position) < tuple_(cursor.at, cursor.post_id, cursor.kind, cursor.actor_id)
            )
        statement = statement.order_by(*(column.desc() for column in position)).limit(limit + 1)
        rows = (await self._session.execute(statement)).all()
        page = rows[:limit]
        posts = [
            PostWithAuthor(
                id=post.id,
                author_id=post.author_id,
                author_handle=None if closed_at else handle,
                author_deleted=closed_at is not None,
                content=post.content,
                created_at=post.created_at,
                likes_count=post.likes_count,
                retweets_count=post.retweets_count,
                replies_count=post.replies_count,
                parent_id=post.parent_id,
                liked_by_me=liked,
                retweeted_by_me=retweeted,
                activity_at=at,
                retweeted_by=shared_by,
                retweeter_id=actor if kind else None,
            )
            for post, handle, closed_at, at, kind, actor, shared_by, liked, retweeted in page
        ]
        next_cursor = None
        if len(rows) > limit:
            post, _, _, at, kind, actor, *_ = page[-1]
            next_cursor = FeedCursor(at, post.id, kind, actor).encode()
        return posts, next_cursor
