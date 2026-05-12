"""B-COR-09: every response carries an X-Request-ID and every log record
within the request has the same request_id in its record context."""

import logging
import uuid


def test_response_carries_x_request_id_header(app_client) -> None:
    r = app_client.get("/health")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid is not None
    uuid.UUID(rid)  # raises on malformed


def test_respects_inbound_request_id_header(app_client) -> None:
    r = app_client.get(
        "/health",
        headers={"X-Request-ID": "deadbeef-1234-1234-1234-deadbeef0000"},
    )
    assert r.headers.get("x-request-id") == "deadbeef-1234-1234-1234-deadbeef0000"


def test_log_records_have_request_id_attribute(app_client, caplog) -> None:
    caplog.set_level(logging.INFO)
    r = app_client.get("/health")
    assert r.status_code == 200
    # Every log record produced under the filter should have a request_id attr.
    assert all(hasattr(rec, "request_id") for rec in caplog.records)
