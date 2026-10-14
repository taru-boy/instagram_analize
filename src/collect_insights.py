"""
Instagram インサイト収集スクリプト。

collect.py が使う Business Discovery API は like/comment しか返さないため、
リーチ・保存・シェア・プロフィールアクセス・リンククリックなどは取得できない。
本スクリプトは「自分（=妻）のアカウント本体のトークン」を使い、
インサイト系エンドポイントを直接叩いて取得する。

- メディア別インサイト : GET /{media-id}/insights?metric=reach,saved,shares,...
- アカウント別インサイト: GET /{ig-user-id}/insights?metric=profile_views,website_clicks,...&metric_type=total_value
                          &since=<その日0時UTC>&until=<翌日0時UTC>（1日ぶん）

.env は collect.py と共通（ACCESS_TOKEN / VERSION / IG_USER_ID）。新しい環境変数は不要。

フォロワー外リーチ（発見＝新規との出会いの指標）は reach を follower_type で
分解して取得する（reach_follower / reach_non_follower）。これは metric_type=total_value
必須で他メトリックと混在できないため、reach 専用の追加リクエストで取得する。
そのぶんメディア1件あたりのリクエスト数が増えるため、レート制限が気になる場合は
--no-breakdown で無効化できる。

使い方:
    python src/collect_insights.py            # 直近 200 件のメディア＋アカウントを収集
    python src/collect_insights.py --limit 50 # 直近 50 件だけ（レート制限対策）
    python src/collect_insights.py --all      # 全メディアを収集（963件あると時間がかかる）
    python src/collect_insights.py --no-breakdown  # フォロワー外リーチの分解を取らない（リクエスト半減）
    python src/collect_insights.py --account-only --account-backfill 730  # アカウント日次を過去2年ぶん取り直す
"""

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from collect_utils import api_get, ensure_dir, load_env, today_str

# メディアタイプごとに取得を試みるメトリック。
# タイプ非対応のメトリックは API が #100 エラーを返すため、core にフォールバックする。
# リール（VIDEO/REELS）は profile_visits 非対応（#100。v22.0 で 2026-10-14 に確認）。
# 足すとリクエストごと失敗して total_interactions / views まで落ちるので入れない。
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
ACCOUNT_COLUMNS = ["date", *ACCOUNT_METRICS, "reach_follower", "reach_non_follower"]

# 毎晩取り直すアカウント日次の日数。日次枠は太平洋時間の1日（日本時間16時〜翌16時）で、
# 0時の実行時点では前日の枠がまだ開いている。締まった直近の日（今日−2）から遡って取り直し、
# Meta 側の集計の遅れも吸収する。
ACCOUNT_REFRESH_DAYS = 3

# 投稿別インサイトCSVの列順
MEDIA_INSIGHT_COLUMNS = [
    "id",
    "media_type",
    "timestamp",
    "reach",
    "reach_follower",
    "reach_non_follower",
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
    parser.add_argument(
        "--no-breakdown",
        action="store_true",
        help="フォロワー外リーチ（reach の follower_type 分解）を取得しない。リクエスト数を半減できる。",
    )
    parser.add_argument(
        "--account-backfill",
        type=int,
        default=ACCOUNT_REFRESH_DAYS,
        metavar="N",
        help=f"アカウント日次を締まった直近N日ぶん取り直す（デフォルト{ACCOUNT_REFRESH_DAYS}。API は直近2年まで）",
    )
    parser.add_argument("--account-only", action="store_true", help="メディア別を取らず、アカウント日次だけ収集する")
    args = parser.parse_args()

    env = load_env()
    access_token = env.access_token
    version = env.version
    ig_user_id = env.ig_user_id

    if not all([access_token, version, ig_user_id]):
        print("ACCESS_TOKEN / VERSION / IG_USER_ID が .env にありません。")
        sys.exit(1)

    today = today_str()
    out_dir = os.path.join(env.base_dir, "result", "insights")
    ensure_dir(out_dir)

    limit = None if args.all else args.limit

    if not args.account_only:
        collect_media_insights(version, ig_user_id, access_token, out_dir, today, limit, args)

    # --- アカウント別インサイト（1日ぶんずつ。累積ファイルに上書き）---
    latest = date.today() - timedelta(days=2)
    days = [latest - timedelta(days=i) for i in range(args.account_backfill)]
    account_rows = []
    for i, day in enumerate(days, 1):
        row = fetch_account_insights(
            version, ig_user_id, access_token, day, with_breakdown=not args.no_breakdown
        )
        if not row:
            # 2年より前は #100 で取れない。backfill はそこで打ち切る
            break
        account_rows.append(row)
        if i % 50 == 0:
            print(f"  アカウント日次 {i}/{len(days)} 日取得…")
        time.sleep(args.sleep)
    if not account_rows:
        print("アカウント別インサイトの取得に失敗しました。")
        sys.exit(1)
    account_path = os.path.join(out_dir, f"{ig_user_id}_account_daily.csv")
    upsert_account_daily(account_path, account_rows)
    print(f"アカウント日次を保存: {account_path}（{account_rows[-1]['date']}〜{account_rows[0]['date']}の{len(account_rows)}日）")

    print("インサイト収集が完了しました。")


def collect_media_insights(version, ig_user_id, access_token, out_dir, today, limit, args) -> None:
    """直近 limit 件（None なら全件）のメディア別インサイトを取得し、日付付きCSVに保存する。"""
    media_list = fetch_media_list(version, ig_user_id, access_token, limit, args.sleep)
    print(f"対象メディア: {len(media_list)} 件")
    if not media_list:
        # トークン失効（#190）・API制限（#4）など。空のCSVを書かずに失敗として終える
        print("メディア一覧が取得できなかったため中断します。")
        sys.exit(1)

    rows = []
    for i, media in enumerate(media_list, 1):
        insights = fetch_media_insights(
            version,
            media["id"],
            media["media_type"],
            access_token,
            with_breakdown=not args.no_breakdown,
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
    total = save_media_insights(media_path, df_media)
    print(f"メディア別インサイトを保存: {media_path}（今回 {len(df_media)} 件・ファイル計 {total} 件）")


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
        data = api_get(url)
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
    version: str,
    media_id: str,
    media_type: str,
    access_token: str,
    with_breakdown: bool = True,
) -> dict:
    """
    1メディア分のインサイトを取得して {metric_name: value} の辞書で返す。
    タイプ非対応メトリックで #100 が出た場合は CORE_METRICS でリトライする。
    注: メディア単位の follower_type 分解は v22.0 で非対応（#100 Incompatible
    breakdowns）のため、reach_follower / reach_non_follower はここでは取得しない
    （アカウントレベルの fetch_account_insights でのみ取得する）。`with_breakdown`
    は API 互換のため受けるだけで、メディア単位では実質no-op。
    """
    metrics = MEDIA_METRICS.get(media_type, CORE_METRICS)
    result = _request_media_insights(version, media_id, metrics, access_token)
    if result is None:
        # メトリック非対応などのエラー → 最小セットで再試行
        result = _request_media_insights(version, media_id, CORE_METRICS, access_token)
    result = result or {}
    # メディア単位の follower breakdown は v22.0 で非対応 (#100 Incompatible breakdowns)
    # アカウントレベル (fetch_account_insights) でのみ取得する
    return result


def _request_reach_breakdown(
    version: str, node: str, access_token: str, period: str | None = None, range_param: str = ""
) -> dict | None:
    """
    reach を follow_type（FOLLOWER / NON_FOLLOWER）で分解して取得する。
    アカウントレベル（{ig-user-id}/insights）専用。period=day 必須。
    API が分解を出すのは直近1年ぶんだけ（それより前の日は結果が空になる）。
    非対応・エラー時は None を返す。

    Returns
    -------
    dict | None
        {"reach_follower": int, "reach_non_follower": int}（取れたものだけ）。
    """
    period_param = f"&period={period}" if period else ""
    url = (
        f"https://graph.facebook.com/{version}/{node}"
        f"?metric=reach&breakdown=follow_type&metric_type=total_value{period_param}{range_param}"
        f"&access_token={access_token}"
    )
    data = api_get(url)
    if "error" in data:
        return None
    out = {}
    for item in data.get("data", []):
        if item.get("name") != "reach":
            continue
        for bd in item.get("total_value", {}).get("breakdowns", []):
            for res in bd.get("results", []):
                dims = res.get("dimension_values", [])
                if not dims:
                    continue
                if dims[0] == "FOLLOWER":
                    out["reach_follower"] = res.get("value")
                elif dims[0] == "NON_FOLLOWER":
                    out["reach_non_follower"] = res.get("value")
    if out:
        # 0 の側は結果から省かれる（全員フォロワー外だった日など）ので 0 で埋める
        out.setdefault("reach_follower", 0)
        out.setdefault("reach_non_follower", 0)
    return out or None


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
    data = api_get(url)
    if "error" in data:
        return None
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        if values:
            out[name] = values[0].get("value")
    return out


def _day_range_param(day: date) -> str:
    """その日1日ぶん（UTC 0時〜翌0時）の since/until。

    since/until を付けないと、Meta は今の時刻にかかる2つの日次枠をまとめた値を返す
    （ユニーク数なので2日の和集合。2026-10-14 に確認）。必ず1日を指定する。
    指定した日は太平洋時間の1日（日本時間16時〜翌16時）の枠として返る。
    """
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    until = start + timedelta(days=1)
    return f"&since={int(start.timestamp())}&until={int(until.timestamp())}"


def fetch_account_insights(
    version: str, ig_user_id: str, access_token: str, day: date, with_breakdown: bool = True
) -> dict:
    """
    アカウント全体の、指定した1日ぶんのインサイト
    （profile_views/website_clicks/reach/accounts_engaged）を取得する。
    metric_type=total_value が必須。
    with_breakdown=True のときは同じ日の reach の follower_type 分解
    （reach_follower / reach_non_follower）も追加リクエストで取得してマージする。
    取得できなければ空の dict を返す（API は直近2年より前を #100 で拒否する）。
    """
    metric_str = ",".join(ACCOUNT_METRICS)
    range_param = _day_range_param(day)
    url = (
        f"https://graph.facebook.com/{version}/{ig_user_id}/insights"
        f"?metric={metric_str}&period=day&metric_type=total_value{range_param}"
        f"&access_token={access_token}"
    )
    data = api_get(url)
    if "error" in data:
        print(f"アカウントインサイト（{day}）の取得でエラー: {data['error']}")
        return {}
    out = {"date": day.isoformat()}
    for item in data.get("data", []):
        name = item.get("name")
        total = item.get("total_value", {})
        out[name] = total.get("value")
    if with_breakdown:
        breakdown = _request_reach_breakdown(
            version, f"{ig_user_id}/insights", access_token, period="day", range_param=range_param
        )
        if breakdown:
            out.update(breakdown)
    return out


def upsert_account_daily(path: str, rows: list[dict]) -> None:
    """アカウント日次の累積CSVに rows を date 単位で上書き（無い日は追加）して保存する。"""
    new = pd.DataFrame(rows)
    if os.path.exists(path):
        old = pd.read_csv(path)
        new = pd.concat([old[~old["date"].isin(new["date"])], new], ignore_index=True)
    for col in ACCOUNT_COLUMNS:
        if col not in new.columns:
            new[col] = None
    new[ACCOUNT_COLUMNS].sort_values("date").to_csv(path, index=False)


def save_media_insights(path: str, df_media: pd.DataFrame) -> int:
    """投稿別インサイトを日付付きCSVに保存し、ファイルの件数を返す。

    同じ日のファイルが既にあれば id で結合する（丸ごと上書きすると、0時の200件の後に
    手で --limit 1 を流したときに1件だけになる。2026-10-14 に実際に起きた）。
    列ごとに最後の非欠損値を採るので新しい値が優先され、一時的なエラーで今回の値が
    欠けても取得済みの値は消えない（load_insights_data の groupby.last と同じ方針）。
    """
    df = df_media.copy()
    df["id"] = df["id"].astype(str)
    if os.path.exists(path):
        prev = pd.read_csv(path, dtype={"id": str})
        # reach_follower などの常に空の列は concat の型推定から外す（下で列を揃え直す）
        df = pd.concat(
            [prev.dropna(axis=1, how="all"), df.dropna(axis=1, how="all")], ignore_index=True
        )
        df = df.groupby("id", sort=False, as_index=False).last()
    for col in MEDIA_INSIGHT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df[MEDIA_INSIGHT_COLUMNS].to_csv(path, index=False)
    return len(df)


if __name__ == "__main__":
    main()
