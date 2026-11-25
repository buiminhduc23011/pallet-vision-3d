import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_default_root_is_repository_not_parent():
    from app.main import ROOT

    assert (ROOT / "frontend" / "package.json").is_file()
    assert (ROOT / "backend" / "pyproject.toml").is_file()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data", tmp_path / "config.json", tmp_path / "models")) as client:
        yield client


def test_starts_offline_without_model(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["detector"]["loaded"] is False
    session = client.post("/api/v1/sessions", json={"mode": "offline"}).json()
    assert session["frame"] is None
    assert session["mode"] == "offline"


def test_cannot_capture_without_real_input(client):
    session = client.post("/api/v1/sessions", json={"mode": "offline"}).json()
    result = client.post(f"/api/v1/sessions/{session['id']}/frames", json={})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "NO_FRAME"


def test_config_write_is_atomic_and_optimistic(client):
    config = client.get("/api/v1/config").json()
    config["matching"]["position_tolerance_px"] = 32
    saved = client.put("/api/v1/config", json=config, headers={"If-Match": '"1"'})
    assert saved.status_code == 200
    assert saved.json()["config"]["revision"] == 2
    stale = client.put("/api/v1/config", json=config, headers={"If-Match": '"1"'})
    assert stale.status_code == 412
    disk = json.loads(client.app.state.engine.config.path.read_text())
    assert disk["matching"]["position_tolerance_px"] == 32


def test_missing_reference_is_404_not_pass(client):
    result = client.post(
        "/api/v1/verifications", json={"reference_id": "missing", "inspection_id": "missing"}
    )
    assert result.status_code == 404


def test_model_path_cannot_escape_trusted_directory(client):
    config = client.get("/api/v1/config").json()
    config["detector"]["model_path"] = "../untrusted.pt"
    result = client.put("/api/v1/config", json=config, headers={"If-Match": '"1"'})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "UNTRUSTED_MODEL_PATH"


def test_invalid_image_is_rejected_and_upload_cleaned(client):
    result = client.post("/api/v1/assets", files={"rgb": ("invalid.jpg", b"not an image", "image/jpeg")})
    assert result.status_code == 422
    assert list((client.app.state.engine.root / "uploads").iterdir()) == []


def test_depth_requires_metadata(client):
    result = client.post(
        "/api/v1/assets",
        files={"rgb": ("image.jpg", b"", "image/jpeg"), "depth": ("depth.png", b"", "image/png")},
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "DEPTH_METADATA_REQUIRED"


def test_browser_cross_origin_write_is_rejected(client):
    result = client.post(
        "/api/v1/sessions", json={"mode": "offline"}, headers={"Origin": "https://attacker.invalid"}
    )
    assert result.status_code == 403


def test_idempotent_session_creation_and_conflicting_reuse(client):
    headers = {"Idempotency-Key": "same-request"}
    first = client.post("/api/v1/sessions", json={"mode": "offline"}, headers=headers)
    second = client.post("/api/v1/sessions", json={"mode": "offline"}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    conflict = client.post("/api/v1/sessions", json={"mode": "live"}, headers=headers)
    assert conflict.status_code == 409


def test_history_bounded_and_empty_without_fake_rows(client):
    assert client.get("/api/v1/history").json() == {"items": [], "next_cursor": None}
    assert client.get("/api/v1/history?limit=1000").status_code == 422


def test_worker_failure_is_persisted_and_reflected_in_health(client):
    # A real missing-input failure, no injected camera/model implementation.
    engine = client.app.state.engine
    ticket = engine.submit("missing-file-check", lambda: engine.store.load_frame("does-not-exist"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(ticket["status_url"]).json()
        if job["status"] == "failed":
            break
        time.sleep(0.01)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/v1/health").json()["status"] == "degraded"


def test_websocket_initial_state_has_no_fake_frame(client):
    session = client.post("/api/v1/sessions", json={"mode": "offline"}).json()
    with client.websocket_connect(f"/api/v1/sessions/{session['id']}/events") as socket:
        event = socket.receive_json()
        assert event["type"] == "session.state"
        assert event["payload"]["frame"] is None


def test_chunked_body_limit_applies_without_content_length(client):
    def chunks():
        for _ in range(20):
            yield b" " * 65536

    result = client.post("/api/v1/sessions", content=chunks(), headers={"Content-Type": "application/json"})
    assert result.status_code == 413


def test_json_preflight_rejects_unbounded_payload(client):
    result = client.post(
        "/api/v1/sessions", content=b" " * (1024 * 1024 + 1), headers={"Content-Type": "application/json"}
    )
    assert result.status_code == 413


def test_foreign_websocket_origin_is_rejected(client):
    from starlette.websockets import WebSocketDisconnect

    session = client.post("/api/v1/sessions", json={"mode": "offline"}).json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/sessions/{session['id']}/events", headers={"Origin": "https://attacker.invalid"}
        ):
            pass
