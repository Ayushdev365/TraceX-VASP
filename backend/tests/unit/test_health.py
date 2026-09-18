"""Phase 1 smoke tests: the app boots, meta endpoints answer, errors are uniform."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok_and_dependency_detail(client: TestClient, api_prefix: str) -> None:
    response = client.get(f"{api_prefix}/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["engine_version"]
    assert body["time"].endswith("Z")

    by_name = {dep["name"]: dep for dep in body["dependencies"]}
    assert set(by_name) == {"database", "ethereum_provider", "tron_provider", "auth"}

    # With no keys configured, each provider must say so rather than claim health.
    for name in ("ethereum_provider", "tron_provider", "auth"):
        assert by_name[name]["status"] == "not_configured"
        assert by_name[name]["detail"]

    # The database is probed for real. The SQLite fallback answers, so it reports ok — and
    # its detail says it is a fallback rather than a configured database.
    assert by_name["database"]["status"] == "ok"
    assert "fallback" in by_name["database"]["detail"]


def test_health_sets_request_id_header(client: TestClient, api_prefix: str) -> None:
    response = client.get(f"{api_prefix}/health")
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_id_is_echoed_when_supplied(client: TestClient, api_prefix: str) -> None:
    response = client.get(f"{api_prefix}/health", headers={"X-Request-ID": "req_fixed123"})
    assert response.headers["X-Request-ID"] == "req_fixed123"


def test_public_config_exposes_policy_and_no_secrets(client: TestClient, api_prefix: str) -> None:
    body = client.get(f"{api_prefix}/meta/config").json()

    assert body["hop_depth"] == {"default": 3, "min": 1, "max": 6}
    assert body["attribution"]["score_type"] == "heuristic_investigative_score"
    # The MVP must never present the score as a calibrated probability (DPRD sec.12, sec.20).
    assert body["attribution"]["calibrated"] is False
    assert body["disclaimers"]["lead_not_proof"] == (
        "This output is an investigative lead and not legal proof."
    )
    assert "not a calibrated probability" in body["disclaimers"]["score"]

    # No secret-bearing key may appear in a public payload.
    serialised = str(body).lower()
    for forbidden in ("api_key", "apikey", "database_url", "secret", "token"):
        assert forbidden not in serialised


def test_unknown_route_uses_the_error_envelope(client: TestClient, api_prefix: str) -> None:
    response = client.get(f"{api_prefix}/does-not-exist")
    assert response.status_code == 404

    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"].startswith("req_")
    assert set(error) == {"code", "message", "details", "request_id"}


def test_openapi_documents_the_claim_posture(client: TestClient, api_prefix: str) -> None:
    schema = client.get(f"{api_prefix}/openapi.json").json()
    assert "investigative lead and not legal proof" in schema["info"]["description"]
