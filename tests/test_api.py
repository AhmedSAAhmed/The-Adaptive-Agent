from fastapi.testclient import TestClient

from app.main import create_app


def test_health_and_webhook_requires_running_session() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json()["ok"]
        r = c.post("/api/events", json={"key": "order.ORD-7781.status", "value": "picked_up"})
        assert r.status_code == 409
        assert len(c.get("/api/scenarios").json()) == 3
        assert c.get("/api/runs/nope/trace.md").text.startswith("# Run not found")
