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


_INSIGHT_NUMERIC = ["reach", "saved", "shares", "total_interactions", "profile_visits", "views"]


def load_insights_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    """
    result/insights/ の全 *_media_insights_*.csv を統合し、id ごとに最新値を残して返す。

    日次で直近N件のみ収集しても、過去に --all で取得した全履歴のカバレッジが
    失われないよう、古い→新しい順に統合し、id ごとに「最新の非欠損値」を採用する。
    （ファイル名末尾が YYYY-MM-DD のため sorted で古い→新しい順になり、
    　groupby.last() がグループ内の最新の非NULL値を返す。）

    Returns
    -------
    pd.DataFrame
        投稿ID別インサイト（id, reach, saved, shares, total_interactions, profile_visits, views）。
        データが無い場合は空のDataFrame。
    """
    ins_dir = os.path.join(result_dir, "insights")
    files = sorted(glob.glob(os.path.join(ins_dir, "*_media_insights_*.csv")))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception:
            continue
        if df.empty or "id" not in df.columns:
            continue
        df["id"] = df["id"].astype(str)
        for col in _INSIGHT_NUMERIC:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    # id ごとに最新の非欠損値を採用（古い→新しい順なので last が最新値）
    return combined.groupby("id", as_index=False).last()


def load_account_insights_data(result_dir: str = RESULT_DIR) -> pd.DataFrame:
    """
    result/insights/ の全 *_account_insights_*.csv を読み込み、日次推移として返す。

    Returns
    -------
    pd.DataFrame
        date, profile_views, website_clicks, reach, accounts_engaged の日次データ。
    """
    ins_dir = os.path.join(result_dir, "insights")
    files = sorted(glob.glob(os.path.join(ins_dir, "*_account_insights_*.csv")))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
            if not df.empty:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for col in ["profile_views", "website_clicks", "reach", "accounts_engaged"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def merge_insights(df_media: pd.DataFrame, df_insights: pd.DataFrame) -> pd.DataFrame:
    """
    メディアデータ（load_media_data）にインサイト列を id で結合する。
    インサイト未取得の投稿は欠損（NaN）のまま残す。
    保存率 saved_rate（saved/reach）も算出する。
    """
    if df_media.empty:
        return df_media
    df = df_media.copy()
    if df_insights.empty or "id" not in df.columns:
        for col in _INSIGHT_NUMERIC + ["saved_rate", "reach_engagement_rate"]:
            df[col] = pd.NA
        return df
    df["id"] = df["id"].astype(str)
    ins_cols = ["id"] + [c for c in _INSIGHT_NUMERIC if c in df_insights.columns]
    df = df.merge(df_insights[ins_cols], on="id", how="left")
    # リーチベースの指標を算出（reach が 0/NaN の場合は計算しない）
    if "reach" in df.columns:
        reach = pd.to_numeric(df["reach"], errors="coerce")
        if "saved" in df.columns:
            df["saved_rate"] = (pd.to_numeric(df["saved"], errors="coerce") / reach * 100).round(2)
        interactions = pd.to_numeric(df["like_count"], errors="coerce").fillna(0) + pd.to_numeric(
            df["comments_count"], errors="coerce"
        ).fillna(0)
        df["reach_engagement_rate"] = (interactions / reach * 100).round(2)
        # reach が無効な行は率も無効に
        df.loc[~(reach > 0), ["saved_rate", "reach_engagement_rate"]] = pd.NA
    return df


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
