"""The backoffice inbox of reports (E5-H7)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from posts_api.infrastructure.database.models import ReportModel, UserProfileModel
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
