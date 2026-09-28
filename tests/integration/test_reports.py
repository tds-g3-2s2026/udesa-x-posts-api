import uuid

import pytest
from sqlalchemy import func, select

from posts_api.api.reports import get_account_review
from posts_api.app.repositories.account_review import AccountReview
from posts_api.infrastructure.database.models import ReportModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

pytestmark = requires_services


async def stored_reports_of(target_id: uuid.UUID) -> int:
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(func.count()).select_from(ReportModel).where(ReportModel.target_id == target_id)
        )
        return found.scalar_one()


class RecordingAccountReview(AccountReview):
    """Stands in for users-api. Records each call together with how many reports
    of that account were already committed when it arrived."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, int]] = []

    async def put_under_review(self, user_id: uuid.UUID) -> None:
        self.calls.append((user_id, await stored_reports_of(user_id)))


@pytest.fixture
def account_review():
    review = RecordingAccountReview()
    app.dependency_overrides[get_account_review] = lambda: review
    yield review
    app.dependency_overrides.pop(get_account_review)


async def report(api, reporter: uuid.UUID, **body):
    return await api.post("/reports", json=body, headers=signed_in_as(reporter))


async def test_e3_h5_ca1_report_is_stored_with_the_chosen_reason(api, account_review):
    reporter, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)

    response = await report(api, reporter, userId=str(target), reason="harassment")

    assert response.status_code == 201
    body = response.json()
    assert body["userId"] == str(target)
    assert body["postId"] is None
    assert body["reason"] == "harassment"
    assert await stored_reports_of(target) == 1


async def test_e3_h5_ca1_a_reason_outside_the_list_is_refused(api, account_review):
    reporter, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)

    response = await report(api, reporter, userId=str(target), reason="i_dont_like_them")

    assert response.status_code == 422
    assert await stored_reports_of(target) == 0


async def test_reporting_a_post_reports_its_author(api, account_review):
    reporter, author = uuid.uuid4(), uuid.uuid4()
    created = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))
    post_id = created.json()["id"]

    response = await report(api, reporter, postId=post_id, reason="spam")

    assert response.status_code == 201
    assert response.json()["userId"] == str(author)
    assert response.json()["postId"] == post_id


async def test_a_report_names_the_account_or_the_post_but_not_both(api, account_review):
    reporter, author = uuid.uuid4(), uuid.uuid4()
    created = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))

    both = await report(
        api, reporter, userId=str(author), postId=created.json()["id"], reason="spam"
    )
    neither = await report(api, reporter, reason="spam")

    assert both.status_code == 422
    assert neither.status_code == 422


async def test_nobody_reports_themselves(api, account_review):
    reporter = uuid.uuid4()
    await given_a_profile(reporter)

    response = await report(api, reporter, userId=str(reporter), reason="spam")

    assert response.status_code == 422
    assert response.json()["type"].endswith("/cannot-report-yourself")


async def test_an_account_that_does_not_exist_cannot_be_reported(api, account_review):
    response = await report(api, uuid.uuid4(), userId=str(uuid.uuid4()), reason="spam")

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_a_post_the_reporter_cannot_see_cannot_be_reported(api, account_review):
    reporter, author = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))

    response = await report(api, reporter, postId=created.json()["id"], reason="spam")

    assert response.status_code == 404
    assert response.json()["type"].endswith("/post-not-found")
    assert await stored_reports_of(author) == 0


async def test_e3_h5_ca3_same_reporter_is_capped_at_one_per_day(api, account_review):
    reporter, target, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await given_a_profile(other)
    first = await report(api, reporter, userId=str(target), reason="spam")
    assert first.status_code == 201

    again = await report(api, reporter, userId=str(target), reason="harassment")

    assert again.status_code == 409
    assert again.json()["type"].endswith("/already-reported")
    assert 0 < int(again.headers["Retry-After"]) <= 24 * 60 * 60
    assert await stored_reports_of(target) == 1
    # The limit is per reported account, not a ban on reporting at all.
    elsewhere = await report(api, reporter, userId=str(other), reason="spam")
    assert elsewhere.status_code == 201


async def test_e3_h5_ca2_six_distinct_reporters_put_the_account_under_review(api, account_review):
    target = uuid.uuid4()
    await given_a_profile(target)

    for _ in range(5):
        response = await report(api, uuid.uuid4(), userId=str(target), reason="spam")
        assert response.status_code == 201
    assert account_review.calls == []

    sixth = await report(api, uuid.uuid4(), userId=str(target), reason="spam")

    assert sixth.status_code == 201
    # Called once the sixth report was committed, never before it.
    assert account_review.calls == [(target, 6)]


async def test_e3_h5_ca2_counts_reporters_and_not_reports(api, account_review):
    target, insistent = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await given_a_profile(insistent)
    # One account that reported on several different days, past the window.
    async with app.state.session_factory() as session:
        for _ in range(4):
            session.add(ReportModel(reporter_id=insistent, target_id=target, reason="spam"))
        await session.commit()

    for _ in range(4):
        response = await report(api, uuid.uuid4(), userId=str(target), reason="spam")
        assert response.status_code == 201

    # Eight reports, five reporters: not enough.
    assert await stored_reports_of(target) == 8
    assert account_review.calls == []


async def test_reports_are_stored_even_when_users_api_does_not_answer(api):
    # No `account_review` fixture: the real client, against a users-api that
    # refuses the connection. ADR-011 keeps the report and retries on the next.
    target = uuid.uuid4()
    await given_a_profile(target)

    for _ in range(6):
        response = await report(api, uuid.uuid4(), userId=str(target), reason="spam")
        assert response.status_code == 201

    assert await stored_reports_of(target) == 6
