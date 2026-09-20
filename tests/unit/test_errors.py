import json
from types import SimpleNamespace

from fastapi.exceptions import RequestValidationError

from posts_api.api.errors import (
    PROBLEM_MEDIA_TYPE,
    problem_error_handler,
    validation_error_handler,
)
from posts_api.app.errors import ProblemError


def fake_request(path: str = "/api/users/@alguien/follow"):
    """The handlers only read the path, to fill `instance`."""
    return SimpleNamespace(url=SimpleNamespace(path=path))


def cuerpo(response) -> dict:
    return json.loads(response.body)


async def test_a_business_error_becomes_problem_details():
    error = ProblemError(
        status=409,
        code="already-following",
        title="No se pudo seguir a la cuenta",
        detail="Ya seguís a esta persona",
    )

    response = await problem_error_handler(fake_request(), error)
    body = cuerpo(response)

    assert response.status_code == 409
    assert response.media_type == PROBLEM_MEDIA_TYPE
    assert body["type"].endswith("/already-following")
    assert body["status"] == 409
    assert body["instance"] == "/api/users/@alguien/follow"
    # Correlates the response with the logs.
    assert len(body["traceId"]) == 32


async def test_the_headers_of_the_error_reach_the_response():
    error = ProblemError(
        status=429,
        code="too-many-requests",
        title="Demasiadas solicitudes",
        detail="Volvé a intentar más tarde",
        headers={"Retry-After": "3600"},
    )

    response = await problem_error_handler(fake_request(), error)

    assert response.headers["Retry-After"] == "3600"


async def test_a_validation_failure_lists_one_entry_per_field():
    error = RequestValidationError(
        [
            {"loc": ("body", "handle"), "msg": "Field required", "type": "missing"},
            {"loc": ("body", "reason"), "msg": "Field required", "type": "missing"},
        ]
    )

    response = await validation_error_handler(fake_request(), error)
    body = cuerpo(response)

    assert response.status_code == 422
    assert body["type"].endswith("/validation-failed")
    # `body` is stripped from the path so the client sees the field name alone.
    assert [e["field"] for e in body["errors"]] == ["handle", "reason"]
