"""ensure_profile keeping its local copy of visibility in step with the token.

The handle is backfilled once and never touched again (it cannot change at
users-api). Visibility is the opposite: it can change at any time, so every
authenticated request is a chance to notice the token disagrees with what is
stored and correct it.
"""

import uuid

from posts_api.infrastructure.database.models import UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

pytestmark = requires_services


async def visibility_of(user_id: uuid.UUID) -> str:
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, user_id)
        return profile.visibility


async def test_a_first_request_creates_the_profile_with_the_token_visibility(api):
    user = uuid.uuid4()

    response = await api.get(
        "/follow-requests", headers=signed_in_as(user, profile_visibility="protected")
    )

    assert response.status_code == 200
    assert await visibility_of(user) == "protected"


async def test_a_later_request_updates_a_stored_profile_that_disagrees(api):
    user = uuid.uuid4()
    await given_a_profile(user, visibility="public")

    await api.get("/follow-requests", headers=signed_in_as(user, profile_visibility="protected"))

    assert await visibility_of(user) == "protected"


async def test_a_request_with_no_visibility_claim_leaves_the_stored_value_alone(api):
    """A token minted before this existed must not reset an account to public."""
    user = uuid.uuid4()
    await given_a_profile(user, visibility="protected")

    await api.get("/follow-requests", headers=signed_in_as(user, profile_visibility=None))

    assert await visibility_of(user) == "protected"


async def test_a_request_that_already_agrees_does_not_touch_the_row(api):
    user = uuid.uuid4()
    await given_a_profile(user, visibility="protected")

    response = await api.get(
        "/follow-requests", headers=signed_in_as(user, profile_visibility="protected")
    )

    assert response.status_code == 200
    assert await visibility_of(user) == "protected"
