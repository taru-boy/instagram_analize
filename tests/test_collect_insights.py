from datetime import date

import pandas as pd

from collect_insights import (
    ACCOUNT_COLUMNS,
    MEDIA_INSIGHT_COLUMNS,
    _day_range_param,
    save_media_insights,
    upsert_account_daily,
)


def test_day_range_param_is_utc_midnight_to_midnight():
    # 2026-10-01 00:00 UTC = 1790812800
    assert _day_range_param(date(2026, 10, 1)) == "&since=1790812800&until=1790899200"


def test_upsert_account_daily_overwrites_by_date(tmp_path):
    path = tmp_path / "daily.csv"
    upsert_account_daily(
        path,
        [
            {"date": "2026-10-01", "reach": 10},
            {"date": "2026-10-02", "reach": 20},
            {"date": "2026-10-03", "reach": 30},
        ],
    )
    upsert_account_daily(
        path,
        [
            {"date": "2026-10-04", "reach": 40, "profile_views": 4},
            {"date": "2026-10-03", "reach": 33},
            {"date": "2026-10-02", "reach": 22},
        ],
    )
    df = pd.read_csv(path)
    assert df.columns.tolist() == ACCOUNT_COLUMNS
    assert df["date"].tolist() == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert df["reach"].tolist() == [10, 22, 33, 40]
    assert df["website_clicks"].isna().all()


def _media(ids, reach, saved=None):
    return pd.DataFrame(
        {
            "id": ids,
            "media_type": "IMAGE",
            "timestamp": "2026-10-01T00:00:00+0000",
            "reach": reach,
            "saved": saved if saved is not None else [1] * len(ids),
        }
    )


def test_save_media_insights_keeps_rows_from_earlier_run(tmp_path):
    path = tmp_path / "media.csv"
    ids = [str(17900000000000000 + i) for i in range(200)]
    assert save_media_insights(path, _media(ids, list(range(200)))) == 200
    # 同じ日に --limit 1 を流しても 200 件のまま、その1件だけ新しい値になる
    assert save_media_insights(path, _media([ids[0]], [999])) == 200
    df = pd.read_csv(path, dtype={"id": str})
    assert df.columns.tolist() == MEDIA_INSIGHT_COLUMNS
    assert set(df["id"]) == set(ids)
    assert df.loc[df["id"] == ids[0], "reach"].item() == 999
    assert df.loc[df["id"] == ids[1], "reach"].item() == 1


def test_save_media_insights_does_not_erase_with_missing_values(tmp_path):
    path = tmp_path / "media.csv"
    save_media_insights(path, _media(["1", "2"], [100, 200], saved=[5, 6]))
    # 一時的なエラーで今回の値が欠けた
    save_media_insights(path, _media(["1"], [None], saved=[None]))
    df = pd.read_csv(path, dtype={"id": str})
    row = df[df["id"] == "1"].iloc[0]
    assert row["reach"] == 100 and row["saved"] == 5


def test_save_media_insights_keeps_long_ids_as_strings(tmp_path):
    path = tmp_path / "media.csv"
    long_id = "17936802879380586"  # float にすると下の桁が壊れる17桁
    save_media_insights(path, _media([long_id], [1]))
    save_media_insights(path, _media([long_id], [2]))
    df = pd.read_csv(path, dtype={"id": str})
    assert df["id"].tolist() == [long_id]
