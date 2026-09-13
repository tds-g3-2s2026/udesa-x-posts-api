import uuid

from posts_api.app.models.follow import (
    FollowRequest,
    FollowRequestStatus,
    ProfileVisibility,
    UserProfile,
)


def build_profile(visibility: ProfileVisibility) -> UserProfile:
    return UserProfile(id=uuid.uuid4(), handle="@alguien", visibility=visibility)


def test_a_public_account_is_followed_without_approval():
    assert not build_profile(ProfileVisibility.PUBLIC).needs_approval


def test_a_protected_account_needs_approval():
    assert build_profile(ProfileVisibility.PROTECTED).needs_approval


def test_an_account_is_public_by_default():
    profile = UserProfile(id=uuid.uuid4(), handle="@alguien")
    assert profile.visibility is ProfileVisibility.PUBLIC
    assert not profile.needs_approval


def test_a_new_profile_starts_with_no_followers():
    profile = UserProfile(id=uuid.uuid4(), handle="@alguien")
    assert profile.followers_count == 0
    assert profile.following_count == 0


def test_a_new_request_is_pending():
    request = FollowRequest(requester_id=uuid.uuid4(), target_id=uuid.uuid4())
    assert request.is_pending


def test_a_resolved_request_is_no_longer_pending():
    request = FollowRequest(
        requester_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        status=FollowRequestStatus.APPROVED,
    )
    assert not request.is_pending
