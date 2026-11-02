import asyncio
import logging
import os
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue
from threading import Thread

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)

from posts_api.config.settings import Settings, get_settings
from posts_api.infrastructure.telemetry import create_meter_provider, instrument

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"


@pytest.fixture
def otlp_receiver():
    received = Queue()

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.put((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def running_app(monkeypatch, otlp_receiver):
    endpoint, _ = otlp_receiver
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:9/test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:9/0")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://test:test@127.0.0.1:9/")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    for signal in ("METRICS", "TRACES", "LOGS"):
        monkeypatch.setenv(
            f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT", f"{endpoint}/v1/{signal.lower()}"
        )
        monkeypatch.setenv(f"OTEL_EXPORTER_OTLP_{signal}_HEADERS", "")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "60000")
    monkeypatch.setenv("OTEL_BSP_SCHEDULE_DELAY", "60000")
    monkeypatch.setenv("OTEL_BLRP_SCHEDULE_DELAY", "60000")

    from posts_api import main

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test:test@127.0.0.1:9/test",
        redis_url="redis://127.0.0.1:9/0",
        rabbitmq_url="amqp://test:test@127.0.0.1:9/",
        internal_api_token="local-test-token",
        auth_redis_url="redis://127.0.0.1:9/2",
        jwt_public_key=os.environ["JWT_PUBLIC_KEY"],
        users_api_url="http://127.0.0.1:9",
        s3_bucket=None,
        otel_exporter_otlp_endpoint=endpoint,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    async def idle(_worker):
        await asyncio.Event().wait()

    monkeypatch.setattr(main.OutboxPublisher, "run", idle)
    monkeypatch.setattr(main.EventConsumer, "run", idle)
    app = FastAPI(lifespan=main.lifespan)
    meter_provider = create_meter_provider()
    tracer_provider = instrument(app, meter_provider)
    monkeypatch.setattr(main, "meter_provider", meter_provider)
    monkeypatch.setattr(main, "tracer_provider", tracer_provider)
    logger_providers = []
    export = main.export

    def observe_export(tracer, span_exporter, log_exporter):
        provider = export(tracer, span_exporter, log_exporter)
        logger_providers.append(provider)
        return provider

    monkeypatch.setattr(main, "export", observe_export)

    @app.get("/api/widgets/{widget_id}")
    async def widget(widget_id: str):
        logging.getLogger("posts_api.lifecycle").info("widget served")
        return {"id": widget_id}

    @app.get("/livez")
    async def probe():
        return {"status": "ok"}

    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level
    try:
        yield app, settings, meter_provider, logger_providers
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()
        for handler in root_logger.handlers[:]:
            if handler not in original_handlers:
                root_logger.removeHandler(handler)
                handler.close()
        root_logger.handlers[:] = original_handlers
        root_logger.setLevel(original_level)
        get_settings.cache_clear()


@pytest.mark.parametrize("exceptional_exit", [False, True])
async def test_lifespan_exports_pending_metrics_and_logs_before_stopping_workers(
    running_app, otlp_receiver, exceptional_exit
):
    app, _, meter_provider, logger_providers = running_app
    _, received = otlp_receiver
    expected_exit = (
        pytest.raises(RuntimeError, match="stop requested") if exceptional_exit else nullcontext()
    )

    with expected_exit:
        async with app.router.lifespan_context(app):
            (reader,) = meter_provider._measurement_consumer._reader_storages
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/livez")).status_code == 200
                response = await client.get(
                    "/api/widgets/private-id?token=secret", headers={"traceparent": TRACEPARENT}
                )
                assert response.status_code == 200
            if exceptional_exit:
                raise RuntimeError("stop requested")

    assert not reader._daemon_thread.is_alive()
    assert not meter_provider._measurement_consumer._reader_storages
    (logger_provider,) = logger_providers
    assert logger_provider.force_flush() is False
    exports = list(received.queue)
    metrics = [
        metric
        for path, body in exports
        if path == "/v1/metrics"
        for resource in ExportMetricsServiceRequest.FromString(body).resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    ]
    assert metrics
    assert all(
        metric.name == "http.server.request.duration" and metric.unit == "s" for metric in metrics
    )
    points = [point for metric in metrics for point in metric.histogram.data_points]
    assert points
    assert all(point.count == 1 for point in points)
    assert all(
        {attribute.key: attribute.value for attribute in point.attributes}[
            "http.route"
        ].string_value
        == "/api/widgets/{widget_id}"
        for point in points
    )
    assert any(
        exemplar.trace_id.hex() == TRACE_ID for point in points for exemplar in point.exemplars
    )
    assert all(
        b"private-id" not in body and b"secret" not in body
        for path, body in exports
        if path == "/v1/metrics"
    )
    logs = [
        record
        for path, body in exports
        if path == "/v1/logs"
        for resource in ExportLogsServiceRequest.FromString(body).resource_logs
        for scope in resource.scope_logs
        for record in scope.log_records
    ]
    assert any(
        record.body.string_value == "widget served" and record.trace_id.hex() == TRACE_ID
        for record in logs
    )


async def test_lifespan_without_endpoint_neither_exports_nor_starts_export_workers(
    running_app, otlp_receiver
):
    app, settings, meter_provider, logger_providers = running_app
    _, received = otlp_receiver
    settings.otel_exporter_otlp_endpoint = None

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/widgets/42")).status_code == 200
        assert not meter_provider._measurement_consumer._reader_storages
        assert logger_providers == []

    assert received.empty()
    assert not meter_provider._measurement_consumer._reader_storages
