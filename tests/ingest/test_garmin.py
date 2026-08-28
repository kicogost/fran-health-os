from __future__ import annotations

from datetime import date

import pytest
from garminconnect.typed import (
    DailySleepDTO,
    DailyStats,
    GarminConnectResponseValidationError,
    HrvData,
    HrvSummary,
    SleepData,
    SleepScores,
    SleepScoreValue,
    TrainingReadiness,
)

from health_os.ingest import garmin

# garminconnect.typed's own ValidationError construction wants a real
# pydantic.ValidationError instance -- easiest way to get one is to trigger a
# real validation failure, rather than hand-building pydantic internals.
try:
    DailyStats.model_validate(["not", "a", "dict"])
    _PYDANTIC_ERROR = None
except Exception as _exc:  # noqa: BLE001
    _PYDANTIC_ERROR = _exc


def _validation_error(method_name: str) -> GarminConnectResponseValidationError:
    return GarminConnectResponseValidationError(
        f"boom in {method_name}", raw=None, pydantic_error=_PYDANTIC_ERROR
    )


class _FakeTyped:
    """Stands in for `Garmin.typed` (a `TypedGarmin`). Returns pre-built
    Pydantic models directly, keyed by cdate -- skips exercising the real
    library's raw-dict validation (that's its job, not ours to re-test), so
    these tests stay focused on `ingest/garmin.py`'s own mapping logic.
    """

    def __init__(self) -> None:
        self.stats: dict[str, DailyStats] = {}
        self.sleep: dict[str, SleepData] = {}
        self.hrv: dict[str, HrvData | None] = {}
        self.readiness: dict[str, list[TrainingReadiness]] = {}
        self.raises: dict[tuple[str, str], Exception] = {}

    def get_stats(self, cdate: str) -> DailyStats:
        if ("get_stats", cdate) in self.raises:
            raise self.raises[("get_stats", cdate)]
        return self.stats.get(cdate, DailyStats())

    def get_sleep_data(self, cdate: str) -> SleepData:
        if ("get_sleep_data", cdate) in self.raises:
            raise self.raises[("get_sleep_data", cdate)]
        return self.sleep.get(cdate, SleepData())

    def get_hrv_data(self, cdate: str) -> HrvData | None:
        if ("get_hrv_data", cdate) in self.raises:
            raise self.raises[("get_hrv_data", cdate)]
        return self.hrv.get(cdate)

    def get_training_readiness(self, cdate: str) -> list[TrainingReadiness]:
        if ("get_training_readiness", cdate) in self.raises:
            raise self.raises[("get_training_readiness", cdate)]
        return self.readiness.get(cdate, [])


class _FakeClient:
    def __init__(self, typed: _FakeTyped | None = None) -> None:
        self.typed = typed or _FakeTyped()
        self.activities: list[dict] = []
        self.raise_on_get_activities: Exception | None = None

    def get_activities_by_date(
        self, startdate: str, enddate: str | None = None, activitytype=None, sortorder=None
    ) -> list[dict]:
        if self.raise_on_get_activities is not None:
            raise self.raise_on_get_activities
        return self.activities


def _one_day() -> tuple[date, date]:
    d = date(2026, 8, 20)
    return d, d


class TestFetchDailyMetrics:
    def test_merges_stats_sleep_hrv_readiness_for_one_date(self) -> None:
        typed = _FakeTyped()
        typed.stats["2026-08-20"] = DailyStats(
            resting_heart_rate=48,
            total_steps=9000,
            active_kilocalories=500.4,
            total_kilocalories=2400.6,
            average_stress_level=22,
            body_battery_highest_value=95,
            body_battery_lowest_value=20,
        )
        typed.sleep["2026-08-20"] = SleepData(
            daily_sleep_dto=DailySleepDTO(
                sleep_time_seconds=7 * 3600,
                deep_sleep_seconds=3600,
                light_sleep_seconds=4 * 3600,
                rem_sleep_seconds=2 * 3600,
                awake_sleep_seconds=300,
                sleep_scores=SleepScores(overall=SleepScoreValue(value=88)),
            )
        )
        typed.hrv["2026-08-20"] = HrvData(
            hrv_summary=HrvSummary(last_night_avg=62.0, status="BALANCED")
        )
        typed.readiness["2026-08-20"] = [TrainingReadiness(score=74, input_context="ACTIVE")]

        client = _FakeClient(typed)
        start, end = _one_day()
        metrics = list(garmin.fetch_daily_metrics(client, start, end))

        assert len(metrics) == 1
        m = metrics[0]
        assert m.date == "2026-08-20"
        assert m.resting_hr == 48
        assert m.steps == 9000
        assert m.active_kcal == 500  # rounded
        assert m.total_kcal == 2401  # rounded
        assert m.stress_avg == 22
        assert m.body_battery_max == 95
        assert m.body_battery_min == 20
        assert m.sleep_total_min == 420  # 7h, from sleep_time_seconds directly
        assert m.sleep_deep_min == 60
        assert m.sleep_light_min == 240
        assert m.sleep_rem_min == 120
        assert m.sleep_awake_min == 5
        assert m.sleep_score == 88
        assert m.hrv_overnight_ms == pytest.approx(62.0)
        assert m.hrv_status == "BALANCED"
        assert m.training_readiness == 74
        assert m.sources is not None
        assert all(v == "garmin" for v in m.sources.values())
        assert set(m.sources) == {
            "resting_hr",
            "steps",
            "active_kcal",
            "total_kcal",
            "stress_avg",
            "body_battery_max",
            "body_battery_min",
            "sleep_total_min",
            "sleep_deep_min",
            "sleep_light_min",
            "sleep_rem_min",
            "sleep_awake_min",
            "sleep_score",
            "hrv_overnight_ms",
            "hrv_status",
            "training_readiness",
        }

    def test_hrv_none_response_is_skipped_not_crashed(self) -> None:
        typed = _FakeTyped()
        typed.stats["2026-08-20"] = DailyStats(resting_heart_rate=50)
        typed.hrv["2026-08-20"] = None  # a documented valid "no HRV data" response
        client = _FakeClient(typed)
        start, end = _one_day()

        metrics = list(garmin.fetch_daily_metrics(client, start, end))
        assert len(metrics) == 1
        assert metrics[0].hrv_overnight_ms is None
        assert metrics[0].hrv_status is None
        assert metrics[0].resting_hr == 50

    def test_day_with_no_data_anywhere_yields_no_row(self) -> None:
        client = _FakeClient()  # every endpoint defaults to empty
        start, end = _one_day()
        assert list(garmin.fetch_daily_metrics(client, start, end)) == []

    def test_training_readiness_prefers_after_wakeup_reset_snapshot(self) -> None:
        typed = _FakeTyped()
        typed.readiness["2026-08-20"] = [
            TrainingReadiness(score=60, input_context="ACTIVE", timestamp="2026-08-20T18:00:00"),
            TrainingReadiness(
                score=80, input_context="AFTER_WAKEUP_RESET", timestamp="2026-08-20T07:00:00"
            ),
        ]
        client = _FakeClient(typed)
        start, end = _one_day()
        metrics = list(garmin.fetch_daily_metrics(client, start, end))
        assert metrics[0].training_readiness == 80

    def test_training_readiness_falls_back_to_latest_timestamp(self) -> None:
        typed = _FakeTyped()
        typed.readiness["2026-08-20"] = [
            TrainingReadiness(score=60, timestamp="2026-08-20T07:00:00"),
            TrainingReadiness(score=90, timestamp="2026-08-20T18:00:00"),
        ]
        client = _FakeClient(typed)
        start, end = _one_day()
        metrics = list(garmin.fetch_daily_metrics(client, start, end))
        assert metrics[0].training_readiness == 90

    def test_validation_error_on_one_endpoint_does_not_block_others(self) -> None:
        typed = _FakeTyped()
        typed.stats["2026-08-20"] = DailyStats(resting_heart_rate=50)
        typed.raises[("get_hrv_data", "2026-08-20")] = _validation_error("get_hrv_data")
        client = _FakeClient(typed)
        start, end = _one_day()
        errors: list[str] = []

        metrics = list(garmin.fetch_daily_metrics(client, start, end, errors=errors))
        assert len(metrics) == 1
        assert metrics[0].resting_hr == 50
        assert metrics[0].hrv_overnight_ms is None
        assert len(errors) == 1
        assert "get_hrv_data" in errors[0]

    def test_covers_every_date_in_inclusive_range(self) -> None:
        typed = _FakeTyped()
        typed.stats["2026-08-01"] = DailyStats(resting_heart_rate=50)
        typed.stats["2026-08-03"] = DailyStats(resting_heart_rate=52)
        client = _FakeClient(typed)
        metrics = {
            m.date: m
            for m in garmin.fetch_daily_metrics(client, date(2026, 8, 1), date(2026, 8, 3))
        }
        # 08-02 has no data anywhere -> correctly absent, not a zeroed/invented row.
        assert set(metrics) == {"2026-08-01", "2026-08-03"}


def _raw_activity(**overrides) -> dict:
    base = {
        "activityId": 123456789,
        "activityName": "Morning Run",
        "startTimeGMT": "2026-08-20 06:30:00",
        "activityType": {"typeId": 1, "typeKey": "running"},
        "duration": 1800.0,
        "distance": 5000.0,
        "averageHR": 150.0,
        "maxHR": 172.0,
        "elevationGain": 40.0,
        "aerobicTrainingEffect": 3.1,
        "anaerobicTrainingEffect": 0.8,
        "avgPower": None,
        "activityTrainingLoad": 85.0,
    }
    base.update(overrides)
    return base


class TestFetchActivities:
    def test_maps_a_real_shaped_activity(self) -> None:
        client = _FakeClient()
        client.activities = [_raw_activity()]
        start, end = _one_day()

        activities = list(garmin.fetch_activities(client, start, end))
        assert len(activities) == 1
        a = activities[0]
        assert a.activity_id == "garmin:123456789"
        assert a.source == "garmin"
        assert a.source_id == "123456789"
        assert a.start_utc == "2026-08-20T06:30:00Z"
        assert a.local_date == "2026-08-20"
        assert a.sport == "running"
        assert a.duration_s == 1800
        assert a.distance_m == pytest.approx(5000.0)
        assert a.avg_hr == 150
        assert a.max_hr == 172
        assert a.elevation_gain_m == pytest.approx(40.0)
        assert a.aerobic_te == pytest.approx(3.1)
        assert a.anaerobic_te == pytest.approx(0.8)
        assert a.training_load == pytest.approx(85.0)
        assert a.sub_sport is None  # properly-typed activity -- name is just a title

    def test_custom_other_profile_name_becomes_sub_sport(self) -> None:
        # Real case, verified 2026-08-28: a custom "Otros" Garmin profile
        # renamed "BJJ" on the watch reports activityType.typeKey="other"
        # (Garmin's own type never changes), but activityName="BJJ" syncs
        # through -- that's what makes these filterable later despite the
        # generic sport.
        client = _FakeClient()
        client.activities = [
            _raw_activity(activityName="BJJ", activityType={"typeId": 4, "typeKey": "other"})
        ]
        activities = list(garmin.fetch_activities(client, *_one_day()))
        assert activities[0].sport == "other"
        assert activities[0].sub_sport == "bjj"

    def test_custom_name_not_reinterpreted_as_sub_sport_for_typed_activities(self) -> None:
        # "Morning Run" is just a title for a properly-typed "running"
        # activity -- must not become sub_sport="morning run".
        client = _FakeClient()
        client.activities = [_raw_activity(activityName="Morning Run")]
        activities = list(garmin.fetch_activities(client, *_one_day()))
        assert activities[0].sub_sport is None

    def test_hr_zones_and_rpe_stay_null_known_gap(self) -> None:
        # See module docstring's "Known gaps": typed.Activity doesn't model
        # hrTimeInZone_*/workoutRpe, and we haven't verified the live endpoint
        # even carries them the same way the bulk export does, so they're
        # left NULL rather than guessed at.
        client = _FakeClient()
        client.activities = [_raw_activity(**{f"hrTimeInZone_{i}": 100.0 * i for i in range(7)})]
        activities = list(garmin.fetch_activities(client, *_one_day()))
        a = activities[0]
        assert a.hr_zone_1_s is None
        assert a.perceived_rpe is None

    def test_skips_activity_missing_id_or_start_time(self) -> None:
        client = _FakeClient()
        client.activities = [_raw_activity(activityId=None)]
        assert list(garmin.fetch_activities(client, *_one_day())) == []

    def test_malformed_activity_is_skipped_and_recorded_not_fatal(self) -> None:
        client = _FakeClient()
        client.activities = [_raw_activity(), {"activityId": 999, "activityType": "not-a-dict"}]
        errors: list[str] = []
        activities = list(garmin.fetch_activities(client, *_one_day(), errors=errors))
        assert len(activities) == 1  # the good one still comes through
        assert len(errors) == 1
        assert "999" in errors[0]

    def test_get_activities_by_date_failure_is_recorded_not_raised(self) -> None:
        client = _FakeClient()
        client.raise_on_get_activities = RuntimeError("network down")
        errors: list[str] = []
        activities = list(garmin.fetch_activities(client, *_one_day(), errors=errors))
        assert activities == []
        assert len(errors) == 1
        assert "network down" in errors[0]

    def test_naive_gmt_timestamp_treated_as_utc(self) -> None:
        # No 'T', no offset -- the documented real-world shape for startTimeGMT.
        client = _FakeClient()
        client.activities = [_raw_activity(startTimeGMT="2026-01-15 23:30:00")]
        activities = list(garmin.fetch_activities(client, *_one_day()))
        assert activities[0].start_utc == "2026-01-15T23:30:00Z"
