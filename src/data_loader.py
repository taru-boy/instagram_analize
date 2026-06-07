import glob
import os
import re

import pandas as pd

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULT_DIR = os.path.join(_BASE, "result")

DAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def load_profile_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(result_dir, "*-profile-*.csv")))
    rows = []
    for f in files:
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", f)
        if not m:
            continue
        try:
            df = pd.read_csv(f, index_col=0)
            row: dict = {"date": pd.to_datetime(m.group(1))}
            for col in ["followers_count", "follows_count", "media_count"]:
                row[col] = pd.to_numeric(df[col].iloc[0], errors="coerce") if col in df.columns else None
            rows.append(row)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame(columns=["date", "followers_count", "follows_count", "media_count"])
    result = pd.DataFrame(rows).sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return result


def load_media_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(result_dir, "*.csv")))
    files = [f for f in files if "-profile-" not in os.path.basename(f)]
    if not files:
        return pd.DataFrame()
    latest = files[-1]
    df = pd.read_csv(latest, index_col=0)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    df["like_count"] = pd.to_numeric(df["like_count"], errors="coerce").fillna(0).astype(int)
    df["comments_count"] = pd.to_numeric(df["comments_count"], errors="coerce").fillna(0).astype(int)
    # タイムスタンプはUTC。JST(+9時間)に変換して分析
    df["timestamp_jst"] = df["timestamp"] + pd.Timedelta(hours=9)
    df["post_date"] = df["timestamp_jst"].dt.normalize()
    df["hour"] = df["timestamp_jst"].dt.hour
    df["weekday"] = df["timestamp_jst"].dt.weekday  # 0=月曜, 6=日曜
    df["day_name"] = df["weekday"].map(lambda x: DAY_JA[x])
    return df


def _normalize_media_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    メディアCSVの共通整形（JST変換・型変換・派生列）。
    load_media_data と同じロジックを競合/ハッシュタグにも適用する。
    """
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    df["like_count"] = pd.to_numeric(df["like_count"], errors="coerce").fillna(0).astype(int)
    df["comments_count"] = pd.to_numeric(df["comments_count"], errors="coerce").fillna(0).astype(int)
    df["timestamp_jst"] = df["timestamp"] + pd.Timedelta(hours=9)
    df["post_date"] = df["timestamp_jst"].dt.normalize()
    df["hour"] = df["timestamp_jst"].dt.hour
    df["weekday"] = df["timestamp_jst"].dt.weekday
    df["day_name"] = df["weekday"].map(lambda x: DAY_JA[x])
    return df


def load_competitor_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    """
    result/competitors/ 内の各競合の最新メディアCSVを読み込み、1つに結合して返す。
    competitor 列に元のユーザー名（ファイル名の username 部分）を付与する。
    """
    comp_dir = os.path.join(result_dir, "competitors")
    files = sorted(glob.glob(os.path.join(comp_dir, "*.csv")))
    files = [f for f in files if "-profile-" not in os.path.basename(f)]
    if not files:
        return pd.DataFrame()

    # username ごとに最新ファイル（日付が新しいもの）を選ぶ
    latest_by_user: dict = {}
    for f in files:
        name = os.path.basename(f)
        m = re.match(r"(.+)_(\d{4}-\d{2}-\d{2})\.csv$", name)
        if not m:
            continue
        username, date = m.group(1), m.group(2)
        if username not in latest_by_user or date > latest_by_user[username][1]:
            latest_by_user[username] = (f, date)

    frames = []
    for username, (f, _date) in latest_by_user.items():
        try:
            df = pd.read_csv(f, index_col=0)
            if df.empty:
                continue
            df = _normalize_media_df(df)
            df["competitor"] = username
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_hashtag_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    """
    result/hashtags/ 内の各タグの最新CSVを読み込み、1つに結合して返す。
    search_hashtag 列に検索したタグ名が入る。
    """
    tag_dir = os.path.join(result_dir, "hashtags")
    files = sorted(glob.glob(os.path.join(tag_dir, "*.csv")))
    if not files:
        return pd.DataFrame()

    latest_by_tag: dict = {}
    for f in files:
        name = os.path.basename(f)
        m = re.match(r"(.+)_(\d{4}-\d{2}-\d{2})\.csv$", name)
        if not m:
            continue
        tag, date = m.group(1), m.group(2)
        if tag not in latest_by_tag or date > latest_by_tag[tag][1]:
            latest_by_tag[tag] = (f, date)

    frames = []
    for tag, (f, _date) in latest_by_tag.items():
        try:
            df = pd.read_csv(f, index_col=0)
            if df.empty:
                continue
            df = _normalize_media_df(df)
            if "search_hashtag" not in df.columns:
                df["search_hashtag"] = tag
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def merge_follower_at_post_date(df_media: pd.DataFrame, df_profile: pd.DataFrame) -> pd.DataFrame:
    if df_profile.empty or df_media.empty:
        df_media["followers_at_post"] = None
        df_media["engagement_rate"] = None
        return df_media
    df_m = df_media.sort_values("post_date").copy()
    df_p = df_profile.sort_values("date")[["date", "followers_count"]].copy()
    merged = pd.merge_asof(
        df_m,
        df_p.rename(columns={"followers_count": "followers_at_post"}),
        left_on="post_date",
        right_on="date",
        direction="nearest",
    )
    # プロフィールCSV収集開始(2025-01-05)より前の投稿は最古のフォロワー数で補完
    oldest = int(df_p["followers_count"].iloc[0])
    merged["followers_at_post"] = merged["followers_at_post"].fillna(oldest).astype(int)
    merged["engagement_rate"] = (
        (merged["like_count"] + merged["comments_count"]) / merged["followers_at_post"] * 100
    ).round(2)
    return merged.reset_index(drop=True)
