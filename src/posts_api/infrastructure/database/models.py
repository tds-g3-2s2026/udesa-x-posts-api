"""The SQLAlchemy tables.

All of them in one module because they reference each other and the metadata is
read as a whole: a model declared somewhere that never gets imported is
invisible when the tables are created.

These classes are storage. The rules about what the graph allows live on the
dataclasses in `app/models/follow.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from posts_api.infrastructure.database.session import Base


class UserProfileModel(Base):
    """Local projection of a user. users-api owns the account."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('public', 'protected')", name="ck_user_profiles_visibility"
        ),
    )

    # Not generated here: it is the same id the account has in users-api.
    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)

    # Empty until a copy of the account arrives from users-api: a valid token
    # carries the id and nothing else. PostgreSQL allows repeated NULLs under a
    # unique index, so the constraint still holds once the handles are there.
    handle: Mapped[str | None] = mapped_column(String(16), unique=True, index=True, default=None)

    # Text plus a CHECK rather than a native ENUM: adding a value is then an
    # ordinary change instead of an ALTER TYPE outside a transaction.
    visibility: Mapped[str] = mapped_column(String(16), default="public", server_default="public")

    # Stored as columns and updated inside the same transaction as the follow,
    # instead of counted on every read.
    followers_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    following_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class FollowModel(Base):
    __tablename__ = "follows"
    __table_args__ = (
        # The pair is the identity of the row, so following twice cannot create
        # a second one; nobody follows themselves.
        CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
        # One for each direction the followers and following screens read in:
        # the fixed side of the query plus the cursor's order column and
        # tiebreak, in that order, so the query matches the index exactly.
        Index("ix_follows_followee_cursor", "followee_id", "created_at", "follower_id"),
        Index("ix_follows_follower_cursor", "follower_id", "created_at", "followee_id"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user_profiles.id"), primary_key=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user_profiles.id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowRequestModel(Base):
    __tablename__ = "follow_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_follow_requests_status",
        ),
        # Only one open request per pair, and only while it is open: a plain
        # unique constraint over the three columns would also forbid a second
        # approved row, so asking again after unfollowing would fail the moment
        # it is approved. Resolved ones stay as history and may repeat.
        Index(
            "uq_follow_requests_open_pair",
            "requester_id",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # Matches the pending listing's query exactly, target plus the
        # cursor's order column and tiebreak. Partial, like the index above,
        # because the listing never reads anything but the pending rows.
        Index(
            "ix_follow_requests_target_pending_cursor",
            "target_id",
            "created_at",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user_profiles.id"), index=True
    )
    # Indexed because the pending list is queried by target: "who asked to
    # follow me" is the screen this table exists for.
    target_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user_profiles.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostModel(Base):
    __tablename__ = "posts"
    __table_args__ = (
        # Serves both "this author's posts" and the feed's per-author lookup
        # while it merges everyone the viewer follows, ordered the same way
        # the cursor reads: created_at, then id as the tiebreak. A plain index
        # on author_id alone would not be enough once the query also sorts.
        Index("ix_posts_author_created", "author_id", "created_at", "id"),
    )

    # Generated by PostgreSQL and not in Python: `uuidv7()` is time-ordered, so
    # the primary key keeps inserts append-mostly in the index and doubles as
    # an implicit chronological cursor for the feed that reads this same
    # table, without exposing a guessable sequence like `bigserial` would on a
    # public endpoint.
    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("user_profiles.id")
    )
    content: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Stored as columns and updated inside the same transaction as the action
    # that moves them, instead of counted on every read, the same reasoning as
    # the follower counters on `UserProfileModel`.
    likes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retweets_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replies_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
