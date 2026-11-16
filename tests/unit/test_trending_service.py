from datetime import UTC, datetime, timedelta

from posts_api.app.models.trending import TrendingTopic
from posts_api.app.services.trending import TrendingService
from tests.fakes import FakeTrendingCache, FakeTrendingRepository

RANKING = [TrendingTopic(tag="udesa", count=3), TrendingTopic(tag="tds", count=1)]


async def test_e2_h11_ca1_the_window_is_the_last_24_hours():
    repository = FakeTrendingRepository(RANKING)
    before = datetime.now(UTC)

    await TrendingService(FakeTrendingCache(), repository).ranking()

    assert (
        before - timedelta(hours=24) <= repository.since <= datetime.now(UTC) - timedelta(hours=24)
    )


async def test_e2_h11_ca2_at_most_ten_topics_are_asked_for():
    repository = FakeTrendingRepository(RANKING)

    await TrendingService(FakeTrendingCache(), repository).ranking()

    assert repository.limit == 10


async def test_e2_h11_ca3_the_second_call_is_served_from_the_cache():
    repository = FakeTrendingRepository(RANKING)
    service = TrendingService(FakeTrendingCache(), repository)

    first = await service.ranking()
    second = await service.ranking()

    assert first == second == RANKING
    assert repository.calls == 1


async def test_e2_h11_ca3_the_ranking_is_stored_with_a_ttl_of_900_seconds():
    cache = FakeTrendingCache()

    await TrendingService(cache, FakeTrendingRepository(RANKING)).ranking()

    assert cache.ttl_seconds == 900


async def test_e2_h11_ca3_once_the_entry_expires_the_ranking_is_computed_again():
    cache = FakeTrendingCache()
    repository = FakeTrendingRepository(RANKING)
    service = TrendingService(cache, repository)
    await service.ranking()

    cache.expire()
    await service.ranking()

    assert repository.calls == 2
