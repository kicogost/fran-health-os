from __future__ import annotations

import sqlite3

from health_os.api.trends import build_trends_payload
from health_os.core import db as db_module
from health_os.core.models import DailyMetric

_CONFIG = {"goals": {"primary": {"date": "2026-10-18", "weight_division_kg": 77.0}}}


def _write_derived(conn: sqlite3.Connection, date: str, value: float, confidence: str) -> None:
    db_module.upsert(
        conn,
        "derived_daily",
        {"date": date, "metric_name": "readiness_score", "value": value, "confidence": confidence},
        ["date", "metric_name"],
        touch_column="computed_at",
    )


class TestBuildTrendsPayload:
    def test_empty_db_returns_empty_series(self, conn: sqlite3.Connection) -> None:
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload == {
            "window_days": 90,
            "series": {},
            "sleep_stages": [],
            "readiness": {
                "label": "Readiness score",
                "raw": [],
                "smoothed": [],
                "coverage_summary": {},
            },
            "insights": [],
        }

    def test_window_filters_out_older_rows(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-01-01", weight_kg=80.0).to_row(), ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-20", weight_kg=79.0).to_row(), ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 30, _CONFIG)
        dates = [p["date"] for p in payload["series"]["weight_kg"]["raw"]]
        assert dates == ["2026-08-20", "2026-08-28"]

    def test_smoothed_series_present_alongside_raw(self, conn: sqlite3.Connection) -> None:
        for d, w in [("2026-08-26", 80.0), ("2026-08-27", 79.5), ("2026-08-28", 79.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, weight_kg=w).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw = payload["series"]["weight_kg"]["raw"]
        smoothed = payload["series"]["weight_kg"]["smoothed"]
        assert len(raw) == len(smoothed) == 3
        # First smoothed point always equals the first raw point (EWMA seed).
        assert smoothed[0]["value"] == raw[0]["value"]

    def test_sleep_stages_only_include_days_with_at_least_one_stage(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-28", sleep_deep_min=60).to_row(),
            ["date"],
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-27", resting_hr=50).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert len(payload["sleep_stages"]) == 1
        assert payload["sleep_stages"][0]["date"] == "2026-08-28"
        assert payload["sleep_stages"][0]["sleep_deep_min"] == 60


class TestReadinessHistory:
    def _seed_daily_metrics(self, conn: sqlite3.Connection, date: str) -> None:
        # build_trends_payload's window cutoff is anchored on daily_metrics'
        # own max date -- readiness history alone isn't enough to produce a
        # non-empty payload, same as every other series on this page.
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date=date, weight_kg=80.0).to_row(), ["date"]
        )

    def test_readiness_history_included_with_confidence(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-27", 54.1, "partial")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        raw = payload["readiness"]["raw"]
        assert [(r["date"], r["value"], r["confidence"]) for r in raw] == [
            ("2026-08-27", 54.1, "partial"),
            ("2026-08-28", 55.8, "full"),
        ]

    def test_coverage_summary_counts_each_confidence_level(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-26", 50.0, "partial")
        _write_derived(conn, "2026-08-27", 54.1, "partial")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["readiness"]["coverage_summary"] == {"partial": 2, "full": 1}

    def test_insufficient_data_rows_excluded_by_null_value(self, conn: sqlite3.Connection) -> None:
        # store_derived_metrics() always writes a row per metric per date --
        # even an insufficient_data one has value=NULL, and NULL isn't a
        # real readiness number to chart.
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-27", None, "insufficient_data")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        assert [r["date"] for r in payload["readiness"]["raw"]] == ["2026-08-28"]

    def test_readiness_history_respects_the_window_cutoff(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-01-01", 60.0, "full")  # well outside a 30-day window
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 30, _CONFIG)
        assert [r["date"] for r in payload["readiness"]["raw"]] == ["2026-08-28"]

    def test_other_metric_names_never_leak_into_readiness_history(
        self, conn: sqlite3.Connection
    ) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        db_module.upsert(
            conn,
            "derived_daily",
            {"date": "2026-08-28", "metric_name": "ctl", "value": 12.3, "confidence": "stale"},
            ["date", "metric_name"],
            touch_column="computed_at",
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["readiness"]["raw"] == []


class TestInsights:
    def test_always_includes_the_four_core_metrics(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        metrics = {i["metric"] for i in payload["insights"]}
        assert {"weight", "sleep", "hrv", "rhr"} <= metrics

    def test_no_data_anywhere_gives_unknown_tone_not_a_crash(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        assert by_metric["sleep"]["tone"] == "unknown"
        assert by_metric["hrv"]["tone"] == "unknown"
        assert by_metric["rhr"]["tone"] == "unknown"

    def test_real_losing_weight_trend_produces_a_good_tone_insight(
        self, conn: sqlite3.Connection
    ) -> None:
        import datetime

        start = datetime.date(2026, 8, 1)
        for i in range(25):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, weight_kg=80.0 - i * 0.05).to_row(),
                ["date"],
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        assert by_metric["weight"]["tone"] == "good"
        assert "losing weight" in by_metric["weight"]["headline"].lower()

    def test_insights_are_not_windowed_by_the_chart_selector(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real weight history goes back further than a 30-day chart window,
        # but the insight itself should still use the full 21-day OLS trend
        # regardless of what window the charts above are set to.
        import datetime

        start = datetime.date(2026, 6, 1)
        for i in range(60):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, weight_kg=80.0 - i * 0.05).to_row(),
                ["date"],
            )
        payload_30 = build_trends_payload(conn, 30, _CONFIG)
        payload_365 = build_trends_payload(conn, 365, _CONFIG)
        weight_30 = next(i for i in payload_30["insights"] if i["metric"] == "weight")
        weight_365 = next(i for i in payload_365["insights"] if i["metric"] == "weight")
        assert weight_30 == weight_365

    def test_headline_and_detail_never_say_bare_hrv_or_rhr(self, conn: sqlite3.Connection) -> None:
        # Real gap found 2026-08-31: hrv_insight()'s headline literally said
        # "HRV" in every branch, inconsistent with rhr_insight() (which
        # correctly spells out "resting heart rate") -- same "no fluff no
        # acronyms" discipline Training's own acronym-lock test already
        # enforces for ctl/atl/tsb/monotony. Checked only against the
        # user-facing headline/detail prose, not the internal "metric" key
        # (which is a real, intentional identifier the frontend keys icons
        # off of, e.g. "hrv"/"rhr" in frontend/src/types/trends.ts -- not
        # prose a reader ever sees).
        import datetime
        import re

        start = datetime.date(2026, 1, 1)
        for i in range(65):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, hrv_overnight_ms=90.0, resting_hr=50.0).to_row(),
                ["date"],
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        # Confirms the "full baseline" branches (not the seed/insufficient
        # placeholder text) actually ran -- a constant series deviates 0 SD
        # from its own baseline, i.e. "balanced"/neutral.
        assert by_metric["hrv"]["tone"] == "neutral"
        assert by_metric["rhr"]["tone"] == "neutral"

        for insight in payload["insights"]:
            text = " ".join(filter(None, [insight.get("headline"), insight.get("detail")]))
            assert not re.search(r"\bhrv\b", text, re.IGNORECASE), text
            assert not re.search(r"\brhr\b", text, re.IGNORECASE), text
