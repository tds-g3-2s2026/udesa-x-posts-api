"""The backoffice inbox of reports (E5-H7)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from posts_api.api.deps import get_users_api
from posts_api.infrastructure.database.models import OutboxModel, ReportModel, UserProfileModel
from posts_api.infrastructure.users_api.account_review import build_users_api_client
from posts_api.main import app
from tests.conftest import issue_token, requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def as_administrator(role: str = "moderator") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(role=role)}"}


async def given_accounts(count: int) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(count)]
    for one in ids:
        await given_a_profile(one)
    return ids


async def given_report(
    reporter: uuid.UUID,
    target: uuid.UUID,
    *,
    at: datetime = NOW,
    reason: str = "spam",
    status: str = "pending",
) -> None:
    """Straight into the table, with its moment and its state under control."""
    async with app.state.session_factory() as session:
        session.add(
            ReportModel(
                reporter_id=reporter, target_id=target, reason=reason, created_at=at, status=status
            )
        )
        await session.commit()


async def cases(api, cursor: str | None = None, headers: dict[str, str] | None = None):
    return await api.get(
        "/admin/posts/reports/cases",
        params={} if cursor is None else {"cursor": cursor},
        headers=as_administrator() if headers is None else headers,
    )


def users_of(response) -> list[str]:
    return [one["userId"] for one in response.json()["items"]]


async def test_e5_h7_ca1_cases_are_sorted_by_distinct_reporters(api):
    a, b, c, *reporters = await given_accounts(6)
    for reporter in reporters[:3]:
        await given_report(reporter, a)
    # One person every day: three reports, but only one reporter.
    for day in range(3):
        await given_report(reporters[0], b, at=NOW - timedelta(days=day))
    for reporter in reporters[:2]:
        await given_report(reporter, c)

    response = await cases(api)

    assert response.status_code == 200
    assert users_of(response) == [str(a), str(c), str(b)]
    by_user = {one["userId"]: one for one in response.json()["items"]}
    assert (by_user[str(b)]["distinctReporters"], by_user[str(b)]["reports"]) == (1, 3)
    assert (by_user[str(a)]["distinctReporters"], by_user[str(a)]["reports"]) == (3, 3)


async def test_e5_h7_ca1_ties_go_to_the_most_recent_report(api):
    older, newer, first, second = await given_accounts(4)
    for reporter in (first, second):
        await given_report(reporter, older, at=NOW - timedelta(hours=2))
    await given_report(first, newer, at=NOW - timedelta(hours=5))
    await given_report(second, newer, at=NOW)

    response = await cases(api)

    # Both have two reporters; the case with the latest report goes first.
    assert users_of(response) == [str(newer), str(older)]


async def test_a_case_says_who_when_and_why(api):
    target, first, second = await given_accounts(3)
    await given_report(first, target, at=NOW - timedelta(days=1), reason="spam")
    await given_report(second, target, at=NOW, reason="harassment")
    await given_report(first, target, at=NOW - timedelta(hours=1), reason="spam")

    [case] = (await cases(api)).json()["items"]

    assert case["handle"] == handle_of(target)
    assert datetime.fromisoformat(case["lastReportedAt"]) == NOW
    # Each reason once, whatever the number of reports that gave it.
    assert case["reasons"] == ["harassment", "spam"]


async def test_reports_already_decided_are_neither_listed_nor_counted(api):
    closed, open_case, first, second = await given_accounts(4)
    await given_report(first, closed, status="dismissed")
    await given_report(second, closed, status="resolved")
    await given_report(first, open_case)
    await given_report(second, open_case, status="dismissed")

    response = await cases(api)

    assert users_of(response) == [str(open_case)]
    assert response.json()["items"][0]["distinctReporters"] == 1


async def test_accounts_already_closed_are_left_out(api):
    closed, reporter = await given_accounts(2)
    await given_report(reporter, closed)
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel).where(UserProfileModel.id == closed).values(deleted_at=NOW)
        )
        await session.commit()

    assert (await cases(api)).json()["items"] == []


async def test_the_inbox_is_paged_with_a_cursor_without_repeating_cases(api):
    reporter = (await given_accounts(1))[0]
    targets = await given_accounts(23)
    for minutes, target in enumerate(targets):
        await given_report(reporter, target, at=NOW - timedelta(minutes=minutes))

    first = await cases(api)
    second = await cases(api, cursor=first.json()["nextCursor"])

    assert len(users_of(first)) == 20
    assert len(users_of(second)) == 3
    assert second.json()["nextCursor"] is None
    # Equal counts: newest report first, and every case exactly once.
    assert users_of(first) + users_of(second) == [str(one) for one in targets]


async def test_a_cursor_that_was_not_handed_out_is_refused(api):
    response = await cases(api, cursor="not-a-cursor")

    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")


async def test_e5_h7_a_user_token_cannot_list_cases(api):
    response = await cases(api, headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-required")


async def test_a_superadmin_lists_cases_too(api):
    response = await cases(api, headers=as_administrator("superadmin"))

    assert response.status_code == 200
    assert response.json() == {"items": [], "nextCursor": None}


class FakeUsersApi:
    """Answers in place of users-api and remembers every call posts-api made."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        # A status code, or "down" for a users-api that does not answer at all.
        self.answer: int | str = 204
        self.identity_answer = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            (request.method, request.url.path, request.headers.get("X-Internal-Token"))
        )
        if request.method == "GET":
            if self.identity_answer == "down":
                raise httpx.ConnectError("users-api is down", request=request)
            if isinstance(self.identity_answer, int):
                return httpx.Response(self.identity_answer)
            body = (
                self.identity_answer
                if self.identity_answer is not None
                else {
                    "id": str(ADMIN),
                    "email": "moderador@udesa.edu.ar",
                }
            )
            return httpx.Response(200, json=body)
        if self.answer == "down":
            raise httpx.ConnectError("users-api is down", request=request)
        return httpx.Response(self.answer)

    def lifts_of(self, user_id: uuid.UUID) -> int:
        return self.calls.count(("DELETE", f"/internal/users/{user_id}/review", "secreto"))


@pytest.fixture
async def users_api():
    """The real client, with users-api's answers under the test's control."""
    fake = FakeUsersApi()
    client = build_users_api_client(
        "http://users-api", "secreto", transport=httpx.MockTransport(fake.handle)
    )
    app.dependency_overrides[get_users_api] = lambda: client
    yield fake
    app.dependency_overrides.pop(get_users_api)
    await client.aclose()


ADMIN = uuid.uuid4()


def as_moderator() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(ADMIN, role='moderator')}"}


async def close(api, action: str, user_id: uuid.UUID, headers: dict[str, str] | None = None):
    return await api.post(
        f"/admin/posts/reports/cases/{user_id}/{action}",
        headers=as_moderator() if headers is None else headers,
    )


async def stored_reports(target: uuid.UUID) -> list[tuple]:
    """Status, who decided and when, oldest report first."""
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(ReportModel.status, ReportModel.decided_by, ReportModel.decided_at)
            .where(ReportModel.target_id == target)
            .order_by(ReportModel.created_at)
        )
        return [tuple(row) for row in found.all()]


async def statuses_of(target: uuid.UUID) -> set[str]:
    return {status for status, _, _ in await stored_reports(target)}


async def given_a_case(reporters: int = 2) -> uuid.UUID:
    target, *others = await given_accounts(reporters + 1)
    for minutes, reporter in enumerate(others):
        await given_report(reporter, target, at=NOW - timedelta(minutes=minutes))
    return target


async def test_e5_h7_ca2_dismiss_marks_pending_reports_and_keeps_the_account(api, users_api):
    target = await given_a_case(reporters=2)
    already_resolved = (await given_accounts(1))[0]
    await given_report(already_resolved, target, at=NOW - timedelta(days=3), status="resolved")
    before = datetime.now(UTC)

    response = await close(api, "dismiss", target)

    assert response.status_code == 204
    resolved, *dismissed = await stored_reports(target)
    assert resolved == ("resolved", None, None)
    assert [(status, by) for status, by, _ in dismissed] == [("dismissed", ADMIN)] * 2
    assert all(at >= before for _, _, at in dismissed)
    assert users_api.calls == [
        ("GET", f"/internal/administrators/{ADMIN}/identity", "secreto"),
        ("DELETE", f"/internal/users/{target}/review", "secreto"),
    ]
    assert (await cases(api)).json()["items"] == []


async def test_e5_h7_ca2_dismissing_twice_changes_nothing(api, users_api):
    target = await given_a_case()
    assert (await close(api, "dismiss", target)).status_code == 204
    first = await stored_reports(target)

    assert (await close(api, "dismiss", target)).status_code == 204

    assert await stored_reports(target) == first
    # Nothing was pending the second time: users-api is not asked again.
    assert users_api.lifts_of(target) == 1


async def test_e5_h7_ca3_resolve_moves_the_case_out_of_pending(api, users_api):
    target = await given_a_case()

    response = await close(api, "resolve", target)

    assert response.status_code == 204
    assert await statuses_of(target) == {"resolved"}
    assert users_api.lifts_of(target) == 1


async def test_e5_h7_ca3_resolved_reports_are_not_listed(api, users_api):
    resolved = await given_a_case(reporters=3)
    still_open = await given_a_case(reporters=1)

    await close(api, "resolve", resolved)

    assert users_of(await cases(api)) == [str(still_open)]


async def test_a_case_stays_open_when_users_api_does_not_answer(api, users_api):
    target = await given_a_case()
    users_api.answer = "down"

    response = await close(api, "dismiss", target)

    assert response.status_code == 503
    assert response.json()["type"].endswith("/users-api-unavailable")
    # Rolled back: the reports wait for the administrator to try again.
    assert await statuses_of(target) == {"pending"}
    assert users_of(await cases(api)) == [str(target)]
    # Tried once more before giving up, as every call between services does.
    assert users_api.lifts_of(target) == 2
    assert await audit_events() == []


async def test_an_account_users_api_no_longer_has_is_closed_anyway(api, users_api):
    target = await given_a_case()
    users_api.answer = 404

    assert (await close(api, "resolve", target)).status_code == 204

    assert await statuses_of(target) == {"resolved"}


async def test_after_a_dismissal_the_review_threshold_counts_from_zero(api, users_api):
    target = await given_a_case(reporters=6)
    await close(api, "dismiss", target)

    response = await api.post(
        "/reports",
        json={"userId": str(target), "reason": "spam"},
        headers=signed_in_as(uuid.uuid4()),
    )

    assert response.status_code == 201
    # Six reporters, but all from a closed case: one pending is far from the
    # threshold, so users-api is not asked to review the account again.
    assert ("POST", f"/internal/users/{target}/review", "secreto") not in users_api.calls


async def test_closing_a_case_leaves_an_audit_entry(api, users_api):
    target = await given_a_case(reporters=2)

    await close(api, "dismiss", target)

    [entry] = await audit_events()
    assert entry["data"]["actor_id"] == str(ADMIN)
    assert entry["data"]["actor_email"] == "moderador@udesa.edu.ar"
    assert entry["data"]["action"] == "report.dismissed"
    assert entry["data"]["target_type"] == "user"
    assert entry["data"]["target_id"] == str(target)
    assert entry["data"]["details"] == {"reports_count": 2}


async def test_closing_a_case_with_nothing_pending_does_not_reach_users_api(api, users_api):
    response = await close(api, "dismiss", uuid.uuid4())

    assert response.status_code == 204
    assert users_api.calls == []


@pytest.mark.parametrize("action", ["dismiss", "resolve"])
async def test_e5_h7_a_user_token_cannot_close_cases(api, users_api, action):
    target = await given_a_case()

    response = await close(api, action, target, headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 403
    assert await statuses_of(target) == {"pending"}


async def audit_events():
    async with app.state.session_factory() as session:
        return list(
            await session.scalars(
                select(OutboxModel.payload).where(OutboxModel.type == "admin.action_recorded.v1")
            )
        )
