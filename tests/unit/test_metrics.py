import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from posts_api.infrastructure.telemetry import (
    HTTP_DURATION_BUCKETS,
    create_meter_provider,
    instrument,
)

CALLER_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
CALLER_TRACEPARENT = f"00-{CALLER_TRACE_ID}-00f067aa0ba902b7-01"


@pytest.fixture
def metrics():
    app = FastAPI()
    reader = InMemoryMetricReader()
    meter_provider = create_meter_provider(reader)
    tracer_provider = instrument(app, meter_provider)

    @app.get("/api/posts/{post_id}")
    async def post(post_id: str):
        return {"id": post_id}

    @app.get("/api/failure")
    async def failure():
        raise HTTPException(status_code=503)

    @app.get("/api/unhandled")
    async def unhandled():
        raise RuntimeError("unavailable dependency")

    @app.get("/healthcheck")
    @app.get("/livez")
    async def health():
        return {"status": "ok"}

    async def call(path: str, *, traceparent: str | None = None):
        headers = {"traceparent": traceparent} if traceparent else {}
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers=headers,
        ) as client:
            return await client.get(path)

    def recorded():
        data = reader.get_metrics_data()
        if data is None:
            return []
        return [
            metric
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        ]

    yield call, recorded, reader

    tracer_provider.shutdown()
    meter_provider.shutdown()


async def test_http_durations_use_seconds_and_shared_service_objective_boundaries(metrics):
    call, recorded, _ = metrics

    await call("/api/posts/123")

    (metric,) = recorded()
    assert metric.name == "http.server.request.duration"
    assert metric.unit == "s"
    (point,) = metric.data.data_points
    assert point.count == 1
    assert point.sum >= 0
    assert point.explicit_bounds == HTTP_DURATION_BUCKETS
    assert {0.3, 0.4, 0.5, 0.8} <= set(point.explicit_bounds)


async def test_ids_and_queries_do_not_split_the_http_duration_series(metrics):
    call, recorded, _ = metrics

    await call("/api/posts/123?token=first-secret")
    await call("/api/posts/456?cursor=another-secret")

    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.count == 2
    assert dict(point.attributes) == {
        "http.request.method": "GET",
        "http.route": "/api/posts/{post_id}",
        "http.response.status_code": 200,
    }
    assert "secret" not in repr(point.attributes)


@pytest.mark.parametrize(
    "path", ["/healthcheck", "/livez", "/healthcheck?token=secret", "/livez?probe=1"]
)
async def test_probes_do_not_record_http_metrics(metrics, path):
    call, recorded, _ = metrics

    await call(path)

    assert recorded() == []


@pytest.mark.parametrize("resource", ["healthcheck", "livez"])
async def test_nested_resource_names_are_not_excluded_as_probe_paths(metrics, resource):
    call, recorded, _ = metrics

    response = await call(f"/api/posts/{resource}?token=secret")

    assert response.status_code == 200
    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.attributes["http.route"] == "/api/posts/{post_id}"
    assert point.count == 1


async def test_http_failures_are_counted_with_their_response_status(metrics):
    call, recorded, _ = metrics

    response = await call("/api/failure")

    assert response.status_code == 503
    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.attributes["http.response.status_code"] == 503
    assert point.count == 1


async def test_unknown_paths_do_not_record_arbitrary_paths_or_identifiers(metrics):
    call, recorded, _ = metrics

    await call("/unknown/one-secret")
    await call("/unknown/another-secret")

    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.attributes == {"http.request.method": "GET", "http.response.status_code": 404}
    assert point.count == 2


async def test_unhandled_failures_record_server_errors(metrics):
    call, recorded, _ = metrics

    assert (await call("/api/unhandled")).status_code == 500

    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.attributes["http.response.status_code"] == 500
    assert point.count == 1


async def test_http_exemplars_keep_the_callers_trace_without_metric_labels(metrics):
    call, recorded, _ = metrics

    await call("/api/posts/123", traceparent=CALLER_TRACEPARENT)

    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert "trace_id" not in point.attributes
    assert point.exemplars
    exemplar = point.exemplars[0]
    assert format(exemplar.trace_id, "032x") == CALLER_TRACE_ID
    assert exemplar.span_id != 0


async def test_unsampled_requests_count_without_retaining_exemplars(metrics):
    call, recorded, _ = metrics

    await call("/api/posts/123", traceparent=f"00-{CALLER_TRACE_ID}-00f067aa0ba902b7-00")

    (metric,) = recorded()
    (point,) = metric.data.data_points
    assert point.count == 1
    assert not point.exemplars


async def test_metrics_resources_identify_the_service_and_process(metrics):
    call, _, reader = metrics

    await call("/api/posts/123")

    (resource,) = reader.get_metrics_data().resource_metrics
    assert resource.resource.attributes["service.name"] == "posts-api"
    assert resource.resource.attributes["service.instance.id"]


async def test_http_metrics_can_start_without_an_external_reader():
    app = FastAPI()
    meter_provider = create_meter_provider()
    tracer_provider = instrument(app, meter_provider)

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/ping")).status_code == 200

    tracer_provider.shutdown()
    meter_provider.shutdown()
