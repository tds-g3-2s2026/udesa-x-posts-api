"""What the service reports about itself: a trace per request and its logs.

Both leave the pod over OTLP. The exporters read the standard
OTEL_EXPORTER_OTLP_* variables on their own, so nothing here knows where the
data goes.
"""

import logging
import time
from importlib.metadata import version

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

SERVICE_NAME = "posts-api"

# Kubernetes probes hit these every few seconds. A span and a log line per
# probe would bury the requests somebody actually made.
PROBE_PATHS = ("/healthcheck", "/livez")

request_logger = logging.getLogger("posts_api.requests")


def _resource() -> Resource:
    return Resource.create({"service.name": SERVICE_NAME, "service.version": version("posts-api")})


def instrument(app: FastAPI) -> TracerProvider:
    """Open a span per request, joining the caller's trace, and log each request.

    Must run before the first request, when the middleware stack is built.
    Until `export` adds an exporter the spans stay in the process, which is
    enough for the logs to carry their trace id.
    """

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        if request.url.path in PROBE_PATHS:
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        # The path only: a query string can carry a token.
        request_logger.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "http.response.status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    provider = TracerProvider(resource=_resource())
    # Wraps the whole middleware stack, so the request log above runs inside
    # the span whatever order the middleware was added in.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=",".join(f"{path}$" for path in PROBE_PATHS),
        # One span per ASGI message says nothing the request span does not.
        exclude_spans=["receive", "send"],
    )
    return provider


def export(
    tracer_provider: TracerProvider,
    span_exporter: SpanExporter,
    log_exporter: LogRecordExporter,
) -> LoggerProvider:
    """Send the spans and every log record of the process, each log tagged with its trace.

    The log handler goes on the root logger, so this has to run after any
    `logging.basicConfig(force=True)`, which removes the root handlers.
    """
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    provider = LoggerProvider(resource=_resource())
    provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(logger_provider=provider)
    # The SDK logs its own export failures. Sending those through the exporter
    # that just failed retries forever, and a process with Grafana unreachable
    # never exits. They still reach the pod's output.
    handler.addFilter(lambda record: not record.name.startswith("opentelemetry"))
    logging.getLogger().addHandler(handler)
    return provider
