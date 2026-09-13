import os

import pytest

# Integration tests need PostgreSQL and Redis. docker/docker-compose.dev.yml
# provides both; without the variables the whole integration suite is skipped so
# the unit tests still run on any machine.
HAS_SERVICES = bool(os.getenv("DATABASE_URL") and os.getenv("REDIS_URL"))

requires_services = pytest.mark.skipif(not HAS_SERVICES, reason="needs DATABASE_URL and REDIS_URL")
