# Build stage: uv resolves and installs dependencies into an isolated venv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies are installed before copying the source so the layer cache
# survives any change under src/.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --locked --no-dev

# Tests only. Sits before the final stage because `docker build` without
# --target builds the last one, and that has to be production.
FROM builder AS test

# Without --no-dev: pytest and the test tooling land in the same venv.
RUN uv sync --locked
COPY tests/ ./tests/

# Same privileges as production: as root, a permission bug shows up after deploy.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

CMD ["uv", "run", "--no-sync", "pytest", \
     "--cov=src", "--cov-report=xml", "--cov-report=term", \
     "--junitxml=report.xml"]

# Final stage: only the venv and the source, without uv or build tooling.
FROM python:3.13-slim

# pip is never used at runtime and the libraries it vendors carry the only
# fixable CVEs in this image.
RUN python -m pip uninstall --yes --quiet pip \
    && useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

# urllib and not curl: the slim image ships neither curl nor wget.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthcheck')"]

# One worker per process: scaling is the orchestrator's job. With several workers
# inside the container, a hung one goes unnoticed by every probe.
CMD ["uvicorn", "posts_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
