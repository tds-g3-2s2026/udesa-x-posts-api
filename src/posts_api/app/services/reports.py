"""The rules of reporting an account, E3-H5.

No FastAPI and no SQLAlchemy here, the same shape `PostService` uses.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account
from posts_api.app.models.report import Report, ReportReason
from posts_api.app.repositories.account_review import AccountReview
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.rate_limiter import RateLimiter
from posts_api.app.repositories.reports import ReportRepository

# CA.3: one report per reporter and reported account every 24 hours. Keyed by
# the account and not by the post, so reporting two posts of the same person
# on the same day is reporting that person twice.
RATE_LIMIT_KEY = "report:rate:{reporter_id}:{target_id}"
REPORT_WINDOW_SECONDS = 24 * 60 * 60

# CA.2 says "more than 5" and ADR-011 reads it literally: the sixth distinct
# reporter is the one that puts the account under review.
REVIEW_THRESHOLD = 6


class ReportService:
    def __init__(
        self,
        reports: ReportRepository,
        follows: FollowRepository,
        posts: PostRepository,
        rate_limiter: RateLimiter,
        account_review: AccountReview,
    ) -> None:
        self._reports = reports
        self._follows = follows
        self._posts = posts
        self._rate_limiter = rate_limiter
        self._account_review = account_review

    async def report(
        self,
        reporter: Account,
        *,
        reason: ReportReason,
        user_id: uuid.UUID | None = None,
        post_id: uuid.UUID | None = None,
    ) -> Report:
        """Store the report, or refuse it and say which rule stopped it.

        Exactly one of `user_id` and `post_id` arrives: the schema checks that.
        A post is reported as its author, with the post kept on the row.
        """
        await self._follows.ensure_profile(reporter)
        target_id = await self._target_of(reporter, user_id=user_id, post_id=post_id)

        if target_id == reporter.id:
            raise ProblemError(
                status=422,
                code="cannot-report-yourself",
                title="No se pudo enviar la denuncia",
                detail="No podés denunciarte a vos mismo",
            )

        await self._charge_the_daily_limit(reporter.id, target_id)
        return await self._reports.add(reporter.id, target_id, reason=reason, post_id=post_id)

    async def review_if_due(self, target_id: uuid.UUID) -> None:
        """Ask users-api to review the account once it passed the threshold.

        Runs after the report is committed, never inside its transaction: a
        rollback after the call would leave an account under review because of
        a report that does not exist. Asking on every report past the
        threshold, and not only on the one that crosses it, is what recovers
        from a call that failed: users-api treats a repeated one as a no-op.
        """
        if await self._reports.distinct_reporters_of(target_id) >= REVIEW_THRESHOLD:
            await self._account_review.put_under_review(target_id)

    async def _target_of(
        self, reporter: Account, *, user_id: uuid.UUID | None, post_id: uuid.UUID | None
    ) -> uuid.UUID:
        if post_id is not None:
            # Only a post the reporter can see can be reported: anything else
            # answers the same `404` as `PostService.get`, for the same reason.
            post = await self._posts.find_visible(post_id, viewer_id=reporter.id)
            if post is None:
                raise ProblemError(
                    status=404,
                    code="post-not-found",
                    title="No se pudo enviar la denuncia",
                    detail="El post no existe",
                )
            return post.author_id

        if await self._follows.find_profile(user_id) is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title="No se pudo enviar la denuncia",
                detail="La cuenta que querés denunciar no existe",
            )
        return user_id

    async def _charge_the_daily_limit(self, reporter_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """CA.3 is a window, not a ban: the same counter with an expiry that
        limits follows and posts, allowed one mark per day."""
        key = RATE_LIMIT_KEY.format(reporter_id=reporter_id, target_id=target_id)
        attempts = await self._rate_limiter.hit(key, window_seconds=REPORT_WINDOW_SECONDS)
        if attempts <= 1:
            return

        seconds_left = await self._rate_limiter.seconds_left(key)
        raise ProblemError(
            status=409,
            code="already-reported",
            title="No se pudo enviar la denuncia",
            detail="Ya denunciaste esta cuenta en las últimas 24 horas",
            headers={"Retry-After": str(seconds_left)},
        )
