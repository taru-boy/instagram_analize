import pandas as pd

from insights import STALL_DAYS, posting_cadence

NOW = pd.Timestamp("2026-10-14 12:00")


def _posts(days_ago):
    return pd.DataFrame({"timestamp_jst": [NOW - pd.Timedelta(days=d) for d in days_ago]})


def test_empty_or_single_post_returns_empty():
    assert posting_cadence(pd.DataFrame(), now=NOW) == {}
    assert posting_cadence(_posts([3]), now=NOW) == {}


def test_stall_when_no_post_for_stall_days():
    # 前90日は週1ペースだったが、最後の投稿から STALL_DAYS 日経った
    result = posting_cadence(_posts([STALL_DAYS, *range(35, 120, 7)]), now=NOW)
    assert result["days_since_last"] == STALL_DAYS
    assert result["trend"] == "停滞"


def test_not_stalled_one_day_before_threshold():
    result = posting_cadence(_posts([STALL_DAYS - 1, *range(35, 120, 7)]), now=NOW)
    assert result["trend"] != "停滞"


def test_pace_down():
    # 前90日は週2本、直近30日は1本（最終投稿は2日前なので停滞ではない）
    result = posting_cadence(_posts([2, *range(31, 120, 3)]), now=NOW)
    assert result["recent_per_week"] < result["older_per_week"] * 0.7
    assert result["trend"] == "ペースダウン"


def test_pace_up():
    # 前90日は月1本、直近30日は週2本
    result = posting_cadence(_posts([*range(1, 30, 3), 40, 70, 100]), now=NOW)
    assert result["trend"] == "ペースアップ"
    assert result["recent_per_week"] == round(10 / (30 / 7), 2)
    assert result["older_per_week"] == round(3 / (90 / 7), 2)
    assert result["days_since_last"] == 1
