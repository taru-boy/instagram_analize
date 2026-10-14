import pandas as pd
import pytest

from data_loader import add_saved_rate_adj


def test_matches_hand_calculation():
    df = pd.DataFrame({"reach": [100, 300], "saved": [10, 6]})
    out = add_saved_rate_adj(df)
    m = 16 / 400  # リーチ加重保存率
    C = 200  # reach 平均
    expected = [(10 + m * C) / (100 + C) * 100, (6 + m * C) / (300 + C) * 100]
    assert out["saved_rate_adj"].astype(float).tolist() == pytest.approx(expected, abs=0.01)


def test_low_reach_is_pulled_toward_mean():
    # リーチ10で保存5（生の保存率50%）のまぐれは、全体平均近くまで下がる
    df = pd.DataFrame({"reach": [10, 1000, 1000], "saved": [5, 20, 20]})
    out = add_saved_rate_adj(df)
    m = 45 / 2010 * 100
    lucky = float(out["saved_rate_adj"].iloc[0])
    assert m < lucky < 5 / 10 * 100
    assert lucky - m < 1


def test_zero_or_missing_reach_stays_na():
    df = pd.DataFrame({"reach": [100, 0, None], "saved": [5, 1, 1]})
    out = add_saved_rate_adj(df)
    assert out["saved_rate_adj"].notna().tolist() == [True, False, False]


def test_missing_columns_gives_na_column():
    out = add_saved_rate_adj(pd.DataFrame({"like_count": [1, 2]}))
    assert out["saved_rate_adj"].isna().all()


def test_does_not_modify_input():
    df = pd.DataFrame({"reach": [100], "saved": [5]})
    add_saved_rate_adj(df)
    assert "saved_rate_adj" not in df.columns
