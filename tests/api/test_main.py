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


class TestServeFrontend:
    """The catch-all that resolves ADR 0005's 'production serving' open item
    -- serves the built React bundle from this same process so
    `uv run python scripts/run_api.py` alone is enough for daily use, no
    separate `npm run dev` process required. Points FRONTEND_DIST_DIR at a
    fake tmp_path dist rather than the real repo build, so these pass
    identically whether or not `npm run build` has actually been run.
    """

    def _make_fake_dist(self, tmp_path: Path) -> Path:
        dist = tmp_path / "fake_dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>shell</html>")
        (dist / "assets").mkdir()
        (dist / "assets" / "index-abc123.js").write_text("console.log('app')")
        return dist

    def test_404s_with_a_helpful_message_when_not_built(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from health_os.api import main as main_module

        monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", Path("/nonexistent/dist"))
        response = client.get("/")
        assert response.status_code == 404
        assert "npm run build" in response.json()["detail"]

    def test_serves_index_html_at_root(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from health_os.api import main as main_module

        monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", self._make_fake_dist(tmp_path))
        response = client.get("/")
        assert response.status_code == 200
        assert response.text == "<html>shell</html>"

    def test_serves_a_real_built_asset(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from health_os.api import main as main_module

        monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", self._make_fake_dist(tmp_path))
        response = client.get("/assets/index-abc123.js")
        assert response.status_code == 200
        assert response.text == "console.log('app')"

    def test_falls_back_to_index_html_for_a_client_side_route(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """React Router routes like /log or /trends aren't real files on
        disk -- a hard refresh or a direct link to one must still get the
        SPA shell so the client-side router can take over, not a 404.
        """
        from health_os.api import main as main_module

        monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", self._make_fake_dist(tmp_path))
        response = client.get("/log")
        assert response.status_code == 200
        assert response.text == "<html>shell</html>"

    def test_api_routes_are_never_shadowed_by_the_catch_all(self, client: TestClient) -> None:
        # No fake dist configured here at all -- if the catch-all somehow
        # matched before this route, this would 404 with the "not built"
        # message instead of the real /api/today 404.
        response = client.get("/api/today")
        assert response.status_code == 404
        assert "daily_metrics" in response.json()["detail"]

    def test_refuses_to_escape_dist_via_path_traversal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Unit-level, not through the HTTP client: httpx/TestClient
        # normalizes ".." out of a URL before it's ever sent, so a
        # request-level test wouldn't actually exercise the traversal
        # guard -- exercise `_safe_dist_file` directly instead.
        from health_os.api import main as main_module

        dist = self._make_fake_dist(tmp_path)
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("do not serve me")
        monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist)

        assert main_module._safe_dist_file("../outside.txt") is None
