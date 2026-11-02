"""Request traces, correlated logs and bounded HTTP duration metrics."""

import logging
import os
import time
from importlib.metadata import version
from uuid import uuid4

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider, TraceBasedExemplarFilter
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.metrics.view import (
    DropAggregation,
    ExplicitBucketHistogramAggregation,
    View,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

SERVICE_NAME = "posts-api"
SERVICE_INSTANCE_ID = str(uuid4())
HTTP_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.3,
    0.4,
    0.5,
    0.75,
    0.8,
    1,
    2.5,
    5,
    7.5,
    10,
)

# Kubernetes probes hit these every few seconds. A span and a log line per
# probe would bury the requests somebody actually made.
PROBE_PATHS = ("/healthcheck", "/livez")

request_logger = logging.getLogger("posts_api.requests")


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": version(SERVICE_NAME),
            "service.instance.id": SERVICE_INSTANCE_ID,
        }
    )


def create_meter_provider(reader: MetricReader | None = None) -> MeterProvider:
    """Collect HTTP durations in seconds, with an optional in-process or OTLP reader."""
    return MeterProvider(
        resource=_resource(),
        metric_readers=[reader] if reader is not None else [],
        exemplar_filter=TraceBasedExemplarFilter(),
        views=[
            View(
                instrument_name="http.server.request.duration",
                attribute_keys={"http.request.method", "http.route", "http.response.status_code"},
                aggregation=ExplicitBucketHistogramAggregation(HTTP_DURATION_BUCKETS),
            ),
            View(instrument_name="*", aggregation=DropAggregation()),
        ],
    )


def instrument(app: FastAPI, meter_provider: MeterProvider | None = None) -> TracerProvider:
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

    # Stable HTTP conventions emit durations in seconds instead of legacy milliseconds.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    provider = TracerProvider(resource=_resource())
    # Wraps the whole middleware stack, so the request log above runs inside
    # the span whatever order the middleware was added in.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        meter_provider=meter_provider,
        excluded_urls=",".join(f"^[^:]+://[^/]+{path}$" for path in PROBE_PATHS),
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
