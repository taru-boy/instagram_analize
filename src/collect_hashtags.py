# ハッシュタグの人気投稿（業界トレンド）を収集するスクリプト
# IG Hashtag Search → top_media の2段リクエストで取得する
#
# ※ API制限に注意:
#   - 1アカウントが照会できるユニークハッシュタグは「7日間で30個」まで
#     （一度照会したタグは7日間カウントに含まれる）
#   - 通常レート制限は 200リクエスト/時/ユーザートークン
#   そのため TREND_HASHTAGS は5〜10個に絞り、cronは週1〜2回程度に抑えること。
import os
import re
import time

import pandas as pd

from collect_utils import api_get, ensure_dir, load_env, today_str


def search_hashtag_id(
    version: str, ig_user_id: str, access_token: str, tag: str
) -> str:
    """
    ハッシュタグ名から hashtag ID を取得する。

    Parameters
    ----------
    version : str
        APIバージョン（例: 'v22.0'）
    ig_user_id : str
        自分のInstagramビジネスアカウントのユーザーID
    access_token : str
        Facebook Graph APIのアクセストークン
    tag : str
        ハッシュタグ名（# は不要）

    Returns
    -------
    str
        hashtag ID。取得できなければ空文字。
    """
    url = (
        f"https://graph.facebook.com/{version}/ig_hashtag_search"
        f"?user_id={ig_user_id}&q={tag}&access_token={access_token}"
    )
    data = api_get(url)
    try:
        return data["data"][0]["id"]
    except (KeyError, IndexError):
        print(f"#{tag} のID取得に失敗: {data}")
        return ""


def get_top_media(
    version: str, ig_user_id: str, access_token: str, hashtag_id: str
) -> list:
    """
    hashtag ID の人気投稿（top_media）を取得する。

    top_media は1リクエストあたりの取得量に厳しい制限があり、件数が多いと code 1
    「Please reduce the amount of data you're asking for」を返す（断続的に発生）。
    そのため media_url は要求せず、小さい limit で取得し、code 1 のときは
    待って limit を下げながら再試行する。

    Returns
    -------
    list
        投稿の辞書のリスト。取得できなければ空リスト。
    """
    # media_url は重く弾かれやすいため要求しない（トレンド分析には不要）
    fields = "id,caption,like_count,comments_count,media_type,permalink,timestamp"

    last = None
    for limit in (5, 3, 2):
        for _attempt in range(2):  # 一時的な失敗に備え各limitで2回試す
            url = (
                f"https://graph.facebook.com/{version}/{hashtag_id}/top_media"
                f"?user_id={ig_user_id}&fields={fields}&limit={limit}"
                f"&access_token={access_token}"
            )
            data = api_get(url)
            if "data" in data:
                return data["data"]

            last = data
            err = data.get("error", {})
            if err.get("code") == 1:
                time.sleep(3)  # 一時的なスロットリング対策で待つ
                continue
            # code 1 以外のエラーは即中断
            print(f"top_media の取得に失敗: {last}")
            return []

    print(f"top_media の取得に失敗（データ量制限が続いています）: {last}")
    return []


def make_hashtag_df(media_list: list, tag: str) -> pd.DataFrame:
    """
    top_media のリストをDataFrameに変換する。
    キャプションからハッシュタグも抽出する（collect.pyと同じ正規表現）。
    """
    rows = []
    for media in media_list:
        caption = media.get("caption", "") or ""
        hash_tag_list = re.findall("#([^\\s→#\\ufeff]*)", caption)
        rows.append(
            {
                "search_hashtag": tag,
                "id": media.get("id"),
                "media_type": media.get("media_type"),
                "media_url": media.get("media_url"),
                "permalink": media.get("permalink"),
                "caption": caption,
                "hashtag": "\n".join(hash_tag_list),
                "timestamp": media.get("timestamp", "")
                .replace("+0000", "")
                .replace("T", " "),
                "like_count": media.get("like_count"),
                "comments_count": media.get("comments_count"),
            }
        )
    return pd.DataFrame(rows)


def main():
    """
    .env の TREND_HASHTAGS（カンマ区切り）を読み、各タグの人気投稿を
    result/hashtags/ 配下に保存する。
    """
    env = load_env()

    raw = os.getenv("TREND_HASHTAGS", "")
    tags = [t.strip().lstrip("#") for t in raw.split(",") if t.strip()]

    if not tags:
        print(
            "TREND_HASHTAGS が .env に設定されていません。"
            "（例: TREND_HASHTAGS=水彩画,イラスト,アート）"
        )
        return

    if len(tags) > 30:
        print("警告: タグが30個を超えています。7日間30タグ制限に注意してください。")

    today = today_str()
    out_dir = os.path.join(env.base_dir, "result", "hashtags")
    ensure_dir(out_dir)

    print(f"トレンドタグ {len(tags)} 件を収集します: {tags}")
    for tag in tags:
        hashtag_id = search_hashtag_id(env.version, env.ig_user_id, env.access_token, tag)
        if not hashtag_id:
            continue
        media_list = get_top_media(env.version, env.ig_user_id, env.access_token, hashtag_id)
        if not media_list:
            continue
        df = make_hashtag_df(media_list, tag)
        df.to_csv(f"{out_dir}/{tag}_{today}.csv")
        print(f"#{tag}: {len(df)} 件保存しました。")


if __name__ == "__main__":
    main()
