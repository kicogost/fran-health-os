"""Smoke test for the FastAPI app itself (api/main.py) — confirms the route
actually wires up correctly end to end (real HTTP request/response through
the real app object), not just that the underlying function works in
isolation (that's tests/api/test_today.py's job).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from health_os.core import db as db_module


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "test_health.db"
    monkeypatch.setenv("HEALTH_OS_DB_PATH", str(db_path))
    db_module.init_db(str(db_path))  # apply migrations before the app touches it

    from health_os.api.main import app

    return TestClient(app)


class TestGetToday:
    def test_returns_404_with_no_data(self, client: TestClient) -> None:
        response = client.get("/api/today")
        assert response.status_code == 404

    def test_returns_200_with_real_shape_once_data_exists(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from health_os.core.models import DailyMetric

        conn = db_module.init_db(str(tmp_path / "test_health.db"))
        try:
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date="2026-08-24", resting_hr=50.0).to_row(),
                ["date"],
            )
        finally:
            conn.close()

        response = client.get("/api/today")
        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-08-24"
        assert "readiness" in body
        assert "sessions" in body
