"""The activity listed on a user's profile (E2-H14): what they posted and what they retweeted.

Its own repository and not a method on `FeedRepository`: the feed reads the
activity of whoever the viewer follows and this reads the activity of one
account, and the two change with different stories. The query has the feed's
shape on purpose, so both order and page the same way and the screen reads one
kind of row.
"""

import uuid

from sqlalchemy import String, literal, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from posts_api.app.feed_pagination import FeedCursor
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.app.repositories.likes import liked_by
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.app.repositories.retweets import retweeted_by
from posts_api.infrastructure.database.models import PostModel, RetweetModel, UserProfileModel


class ProfilePostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_author(
        self,
        author_id: uuid.UUID,
        viewer_id: uuid.UUID,
        *,
        cursor: FeedCursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The account's posts and retweets, most recent activity first.

        A retweet sits where it was shared, not where the original was written,
        the same as in the feed.

        The service already refused a viewer who cannot read this account, but
        `visible_to` stays in the query anyway: a listing of posts that skips it
        is one refactor away from a privacy leak. Here it also hides a retweet
        of an account the viewer cannot read. A deleted post is left out,
        retweeted or not, as in the feed: no public read returns its text. So is
        a post of a closed account, except a reply this account retweeted, which
        stays marked as written by a deleted user, also as in the feed.
        """
        sharer = aliased(UserProfileModel)
        originals = select(
            PostModel.id.label("post_id"),
            PostModel.created_at.label("activity_at"),
            literal(0).label("kind"),
            PostModel.author_id.label("actor_id"),
            literal(None, type_=String).label("shared_by"),
        ).where(
            PostModel.author_id == author_id,
            # Replies are read from the post they answer, as in the feed.
            PostModel.parent_id.is_(None),
        )
        shares = (
            select(
                RetweetModel.post_id,
                RetweetModel.created_at,
                literal(1),
                RetweetModel.user_id,
                sharer.handle,
            )
            .join(sharer, sharer.id == RetweetModel.user_id)
            .where(RetweetModel.user_id == author_id)
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
                    # A reply of a closed account that this account retweeted
                    # stays, as in the feed: the thread it belongs to is kept.
                    keeps_deleted_author=PostModel.parent_id.is_not(None),
                ),
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
