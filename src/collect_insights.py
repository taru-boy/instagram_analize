"""
Instagram インサイト収集スクリプト。

collect.py が使う Business Discovery API は like/comment しか返さないため、
リーチ・保存・シェア・プロフィールアクセス・リンククリックなどは取得できない。
本スクリプトは「自分（=妻）のアカウント本体のトークン」を使い、
インサイト系エンドポイントを直接叩いて取得する。

- メディア別インサイト : GET /{media-id}/insights?metric=reach,saved,shares,...
- アカウント別インサイト: GET /{ig-user-id}/insights?metric=profile_views,website_clicks,...&metric_type=total_value

.env は collect.py と共通（ACCESS_TOKEN / VERSION / IG_USER_ID）。新しい環境変数は不要。

使い方:
    python src/collect_insights.py            # 直近 200 件のメディア＋アカウントを収集
    python src/collect_insights.py --limit 50 # 直近 50 件だけ（レート制限対策）
    python src/collect_insights.py --all      # 全メディアを収集（963件あると時間がかかる）
"""

import argparse
import json
import os
import time
from datetime import datetime as dt

import pandas as pd
import requests
from dotenv import load_dotenv

# メディアタイプごとに取得を試みるメトリック。
# タイプ非対応のメトリックは API が #100 エラーを返すため、core にフォールバックする。
MEDIA_METRICS = {
    "IMAGE": ["reach", "saved", "shares", "total_interactions", "profile_visits"],
    "CAROUSEL_ALBUM": ["reach", "saved", "shares", "total_interactions", "profile_visits"],
    "VIDEO": ["reach", "saved", "shares", "total_interactions", "views"],
    "REELS": ["reach", "saved", "shares", "total_interactions", "views"],
}
# どのタイプでも取れる最小セット（フォールバック用）
CORE_METRICS = ["reach", "saved", "shares"]

# アカウント全体の日次インサイト
ACCOUNT_METRICS = ["profile_views", "website_clicks", "reach", "accounts_engaged"]

# 投稿別インサイトCSVの列順
MEDIA_INSIGHT_COLUMNS = [
    "id",
    "media_type",
    "timestamp",
    "reach",
    "saved",
    "shares",
    "total_interactions",
    "profile_visits",
    "views",
]


def main():
    parser = argparse.ArgumentParser(description="Instagram インサイト収集")
    parser.add_argument("--limit", type=int, default=200, help="収集する直近メディア件数（デフォルト200）")
    parser.add_argument("--all", action="store_true", help="全メディアを収集する")
    parser.add_argument("--sleep", type=float, default=0.3, help="リクエスト間のウェイト秒（レート制限対策）")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))

    access_token = os.getenv("ACCESS_TOKEN")
    version = os.getenv("VERSION")
    ig_user_id = os.getenv("IG_USER_ID")

    if not all([access_token, version, ig_user_id]):
        print("ACCESS_TOKEN / VERSION / IG_USER_ID が .env にありません。")
        return

    today = dt.now().strftime("%Y-%m-%d")
    out_dir = os.path.join(base_dir, "result", "insights")
    os.makedirs(out_dir, exist_ok=True)

    limit = None if args.all else args.limit

    # --- メディア別インサイト ---
    media_list = fetch_media_list(version, ig_user_id, access_token, limit, args.sleep)
    print(f"対象メディア: {len(media_list)} 件")

    rows = []
    for i, media in enumerate(media_list, 1):
        insights = fetch_media_insights(
            version, media["id"], media["media_type"], access_token
        )
        row = {
            "id": media["id"],
            "media_type": media["media_type"],
            "timestamp": media.get("timestamp", ""),
        }
        row.update(insights)
        rows.append(row)
        if i % 20 == 0:
            print(f"  {i}/{len(media_list)} 件取得…")
        time.sleep(args.sleep)

    df_media = pd.DataFrame(rows)
    # 列を揃える（取得できなかった指標も列として残す）
    for col in MEDIA_INSIGHT_COLUMNS:
        if col not in df_media.columns:
            df_media[col] = None
    df_media = df_media[MEDIA_INSIGHT_COLUMNS]
    media_path = os.path.join(out_dir, f"{ig_user_id}_media_insights_{today}.csv")
    df_media.to_csv(media_path, index=False)
    print(f"メディア別インサイトを保存: {media_path}")

    # --- アカウント別インサイト ---
    account_rows = fetch_account_insights(version, ig_user_id, access_token)
    if account_rows:
        df_account = pd.DataFrame([account_rows])
        df_account.insert(0, "date", today)
        account_path = os.path.join(out_dir, f"{ig_user_id}_account_insights_{today}.csv")
        df_account.to_csv(account_path, index=False)
        print(f"アカウント別インサイトを保存: {account_path}")
    else:
        print("アカウント別インサイトの取得に失敗しました。")

    print("インサイト収集が完了しました。")


def fetch_media_list(
    version: str,
    ig_user_id: str,
    access_token: str,
    limit: int | None,
    sleep: float,
) -> list:
    """
    /{ig-user-id}/media をページネーションしながらメディア一覧を取得する。

    Parameters
    ----------
    limit : int | None
        取得する最大件数。None なら全件。

    Returns
    -------
    list
        {"id", "media_type", "timestamp"} の辞書のリスト（新しい順）。
    """
    results = []
    url = (
        f"https://graph.facebook.com/{version}/{ig_user_id}/media"
        f"?fields=id,media_type,timestamp&limit=100&access_token={access_token}"
    )
    while url:
        r = requests.get(url)
        data = json.loads(r.content)
        if "error" in data:
            print(f"メディア一覧の取得でエラー: {data['error']}")
            break
        results.extend(data.get("data", []))
        if limit is not None and len(results) >= limit:
            results = results[:limit]
            break
        url = data.get("paging", {}).get("next")
        if url:
            time.sleep(sleep)
    return results


def fetch_media_insights(
    version: str, media_id: str, media_type: str, access_token: str
) -> dict:
    """
    1メディア分のインサイトを取得して {metric_name: value} の辞書で返す。
    タイプ非対応メトリックで #100 が出た場合は CORE_METRICS でリトライする。
    """
    metrics = MEDIA_METRICS.get(media_type, CORE_METRICS)
    result = _request_media_insights(version, media_id, metrics, access_token)
    if result is None:
        # メトリック非対応などのエラー → 最小セットで再試行
        result = _request_media_insights(version, media_id, CORE_METRICS, access_token)
    return result or {}


def _request_media_insights(
    version: str, media_id: str, metrics: list, access_token: str
) -> dict | None:
    """
    insights エンドポイントを1回叩く。エラー時は None を返す。
    """
    metric_str = ",".join(metrics)
    url = (
        f"https://graph.facebook.com/{version}/{media_id}/insights"
        f"?metric={metric_str}&access_token={access_token}"
    )
    r = requests.get(url)
    data = json.loads(r.content)
    if "error" in data:
        return None
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        if values:
            out[name] = values[0].get("value")
    return out


def fetch_account_insights(version: str, ig_user_id: str, access_token: str) -> dict:
    """
    アカウント全体の日次インサイト（profile_views/website_clicks/reach/accounts_engaged）を取得。
    metric_type=total_value が必須。
    """
    metric_str = ",".join(ACCOUNT_METRICS)
    url = (
        f"https://graph.facebook.com/{version}/{ig_user_id}/insights"
        f"?metric={metric_str}&period=day&metric_type=total_value&access_token={access_token}"
    )
    r = requests.get(url)
    data = json.loads(r.content)
    if "error" in data:
        print(f"アカウントインサイトの取得でエラー: {data['error']}")
        return {}
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        total = item.get("total_value", {})
        out[name] = total.get("value")
    return out


if __name__ == "__main__":
    main()
