"""Tests for api/sync.py — the manual "sync now" endpoint's assembly
function (2026-09-17). Never touches the real Garmin/Health Auto Export/
RENPHO sources: `run_live_sync()` is monkeypatched to a fake result so these
tests exercise only the wiring this module actually owns (summarizing the
sync outcome, recomputing derived_daily for the synced window) — the real
per-source ingestion logic is `tests/ingest/`'s job.
"""

from __future__ import annotations

import sqlite3

import pytest

from health_os.api.sync import run_manual_sync
from health_os.core.dedupe import DedupeResult
from health_os.ingest.live_sync import LiveSyncResult

_CONFIG = {
    "readiness_score": {
        "weight_hrv": 0.35,
        "weight_sleep": 0.25,
        "weight_rhr": 0.15,
        "weight_subjective": 0.25,
    },
}


def _fake_result(**overrides: object) -> LiveSyncResult:
    defaults: dict[str, object] = {
        "garmin_ok": True,
        "health_auto_export_ok": True,
        "renpho_csv_ok": True,
        "dedupe": DedupeResult(groups_merged=0, rows_deleted=0, winners=[], fk_conflicts=[]),
        "start_date": "2026-09-15",
        "end_date": "2026-09-17",
    }
    defaults.update(overrides)
    return LiveSyncResult(**defaults)  # type: ignore[arg-type]


class TestRunManualSync:
    def test_success_shape(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("health_os.api.sync.run_live_sync", lambda conn, days=3: _fake_result())
        result = run_manual_sync(conn, _CONFIG)

        assert result["status"] == "success"
        assert result["sources"] == {
            "garmin": True,
            "health_auto_export": True,
            "renpho_csv": True,
        }
        assert result["window"] == {"start_date": "2026-09-15", "end_date": "2026-09-17"}
        assert result["dedupe"] == {"groups_merged": 0, "rows_deleted": 0}
        assert "synced_at" in result

    def test_one_failed_source_reports_partial_failure_not_an_exception(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "health_os.api.sync.run_live_sync",
            lambda conn, days=3: _fake_result(garmin_ok=False),
        )
        result = run_manual_sync(conn, _CONFIG)

        assert result["status"] == "partial_failure"
        assert result["sources"]["garmin"] is False

    def test_recomputes_derived_daily_for_the_synced_window(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "health_os.api.sync.run_live_sync",
            lambda conn, days=3: _fake_result(start_date="2026-09-16", end_date="2026-09-17"),
        )
        result = run_manual_sync(conn, _CONFIG)

        # Design principle 6: every metric gets a row (even "insufficient_data"
        # on an empty DB) -- a non-zero count confirms compute/store actually
        # ran for the real window `run_live_sync` reported, not a hardcoded one.
        assert result["derived_metrics_rows_written"] > 0
        rows = conn.execute("SELECT DISTINCT date FROM derived_daily ORDER BY date").fetchall()
        assert [r["date"] for r in rows] == ["2026-09-16", "2026-09-17"]

    def test_dedupe_summary_reflects_real_merges(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "health_os.api.sync.run_live_sync",
            lambda conn, days=3: _fake_result(
                dedupe=DedupeResult(
                    groups_merged=2,
                    rows_deleted=2,
                    winners=["garmin:1", "garmin:2"],
                    fk_conflicts=[],
                )
            ),
        )
        result = run_manual_sync(conn, _CONFIG)
        assert result["dedupe"] == {"groups_merged": 2, "rows_deleted": 2}
