"""The blocking rules, with the storage swapped for plain sets.

What these cover is the order and the answers of the rules: which error comes
back, and what gets torn down. What only PostgreSQL can prove, the visibility
filter, the atomic counters and `ON CONFLICT`, lives in the integration suite.
"""

import uuid

import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, BlockedAccount, UserProfile
from posts_api.app.services.blocks import BlockService
from posts_api.app.services.follow_listings import FollowListingService
from posts_api.app.services.follows import FollowService


class InMemoryFollows:
    def __init__(self, *known: uuid.UUID) -> None:
        self.profiles = {one: UserProfile(id=one) for one in known}
        self.edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    async def ensure_profile(self, account: Account) -> UserProfile:
        return self.profiles.setdefault(account.id, UserProfile(id=account.id))

    async def find_profile(self, user_id: uuid.UUID) -> UserProfile | None:
        return self.profiles.get(user_id)

    async def is_following(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        return (follower_id, followee_id) in self.edges

    async def add_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        self.edges.add((follower_id, followee_id))

    async def remove_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        if (follower_id, followee_id) not in self.edges:
            return False
        self.edges.remove((follower_id, followee_id))
        return True

    async def move_counters(
        self, follower_id: uuid.UUID, followee_id: uuid.UUID, *, by: int
    ) -> None:
        self.profiles[followee_id].followers_count += by
        self.profiles[follower_id].following_count += by

    def follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        self.edges.add((follower_id, followee_id))
        self.profiles[followee_id].followers_count += 1
        self.profiles[follower_id].following_count += 1


class InMemoryRequests:
    def __init__(self) -> None:
        self.pending: set[tuple[uuid.UUID, uuid.UUID]] = set()
        self.cancelled: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def cancel(self, requester_id: uuid.UUID, target_id: uuid.UUID) -> bool:
        if (requester_id, target_id) not in self.pending:
            return False
        self.pending.remove((requester_id, target_id))
        self.cancelled.append((requester_id, target_id))
        return True


class InMemoryBlocks:
    def __init__(self) -> None:
        self.pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()

    async def add(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> bool:
        if (blocker_id, blocked_id) in self.pairs:
            return False
        self.pairs.add((blocker_id, blocked_id))
        return True

    async def remove(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        self.pairs.discard((blocker_id, blocked_id))

    async def has_blocked(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> bool:
        return (blocker_id, blocked_id) in self.pairs

    async def blocked_by(self, blocker_id, *, cursor=None) -> tuple[list[BlockedAccount], None]:
        return [], None


class NeverLimited:
    async def hit(self, key: str, *, window_seconds: int) -> int:
        return 1

    async def seconds_left(self, key: str) -> int:
        return 0


def block_service(follows, requests=None, blocks=None) -> BlockService:
    return BlockService(blocks or InMemoryBlocks(), follows, requests or InMemoryRequests())


def follow_service(follows, blocks) -> FollowService:
    return FollowService(
        follows, InMemoryRequests(), blocks, NeverLimited(), follow_limit=50, window_seconds=3600
    )


async def test_blocking_yourself_is_refused_before_anything_is_written():
    me = uuid.uuid4()
    follows = InMemoryFollows()
    blocks = InMemoryBlocks()

    with pytest.raises(ProblemError) as refused:
        await block_service(follows, blocks=blocks).block(Account(id=me), me)

    assert (refused.value.status, refused.value.code) == (409, "cannot-block-yourself")
    assert follows.profiles == {}
    assert blocks.pairs == set()


async def test_blocking_an_account_that_does_not_exist_records_nothing():
    me = uuid.uuid4()
    blocks = InMemoryBlocks()

    with pytest.raises(ProblemError) as refused:
        await block_service(InMemoryFollows(), blocks=blocks).block(Account(id=me), uuid.uuid4())

    assert refused.value.status == 404
    assert blocks.pairs == set()


async def test_e3_h4_ca3_blocking_tears_down_both_directions_and_their_counters():
    me, other = uuid.uuid4(), uuid.uuid4()
    follows = InMemoryFollows(me, other)
    follows.follow(me, other)
    follows.follow(other, me)

    await block_service(follows).block(Account(id=me), other)

    assert follows.edges == set()
    for account in (me, other):
        profile = follows.profiles[account]
        assert (profile.followers_count, profile.following_count) == (0, 0)


async def test_blocking_withdraws_the_pending_requests_in_both_directions():
    me, other = uuid.uuid4(), uuid.uuid4()
    requests = InMemoryRequests()
    requests.pending = {(me, other), (other, me)}

    await block_service(InMemoryFollows(me, other), requests=requests).block(Account(id=me), other)

    assert requests.pending == set()


async def test_blocking_twice_does_not_tear_anything_down_the_second_time():
    me, other = uuid.uuid4(), uuid.uuid4()
    requests = InMemoryRequests()
    requests.pending = {(other, me)}
    service = block_service(InMemoryFollows(me, other), requests=requests)

    await service.block(Account(id=me), other)
    await service.block(Account(id=me), other)

    assert requests.cancelled == [(other, me)]


async def test_unblocking_lifts_the_block_and_leaves_the_follows_removed():
    me, other = uuid.uuid4(), uuid.uuid4()
    follows = InMemoryFollows(me, other)
    follows.follow(me, other)
    blocks = InMemoryBlocks()
    service = block_service(follows, blocks=blocks)

    await service.block(Account(id=me), other)
    await service.unblock(Account(id=me), other)

    assert blocks.pairs == set()
    assert follows.edges == set()


async def test_the_blocked_account_gets_the_same_answer_as_a_missing_one_when_following():
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    follows = InMemoryFollows(blocker, blocked)
    blocks = InMemoryBlocks()
    blocks.pairs = {(blocker, blocked)}
    service = follow_service(follows, blocks)

    with pytest.raises(ProblemError) as to_blocker:
        await service.follow(Account(id=blocked), blocker)
    with pytest.raises(ProblemError) as to_nobody:
        await service.follow(Account(id=blocked), uuid.uuid4())

    seen = (to_blocker.value.status, to_blocker.value.code, to_blocker.value.detail)
    assert seen == (to_nobody.value.status, to_nobody.value.code, to_nobody.value.detail)


async def test_the_blocker_is_told_to_unblock_before_following():
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    blocks = InMemoryBlocks()
    blocks.pairs = {(blocker, blocked)}

    with pytest.raises(ProblemError) as refused:
        await follow_service(InMemoryFollows(blocker, blocked), blocks).follow(
            Account(id=blocker), blocked
        )

    assert (refused.value.status, refused.value.code) == (409, "account-blocked")


async def test_e3_h4_ca4_the_blocked_account_cannot_read_the_blockers_lists():
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    blocks = InMemoryBlocks()
    blocks.pairs = {(blocker, blocked)}
    service = FollowListingService(None, InMemoryFollows(blocker, blocked), blocks)

    with pytest.raises(ProblemError) as refused:
        await service.followers_of(blocker, Account(id=blocked))

    assert (refused.value.status, refused.value.code) == (404, "user-not-found")
