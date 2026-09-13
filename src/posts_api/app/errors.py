"""The error the business raises when a rule is not met.

It lives here and not in `api/` because the services raise it, and they know
nothing about HTTP. Turning it into a response is `api/errors.py`'s job.
"""


class ProblemError(Exception):
    """An error that becomes a Problem Details response.

    The format is the one documented in ARQUITECTURA.md, "Formato de error":
    RFC 9457, which obsoletes RFC 7807 and keeps the same media type.
    """

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}
