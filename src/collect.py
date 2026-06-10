# 必要なモジュールをimport
import os
import re
from datetime import datetime as dt

import pandas as pd

from collect_utils import api_get, ensure_dir, load_env, today_str


def main():
    """
    メイン関数
    """
    env = load_env()
    path = os.path.join(env.base_dir, "result")
    collect_account(env.version, env.ig_user_id, env.target_user_id, env.access_token, today_str(), path)


def collect_account(
    version: str,
    ig_user_id: str,
    user_id: str,
    access_token: str,
    today: str,
    out_dir: str,
) -> bool:
    """
    指定した1アカウントのプロフィール情報・投稿一覧を取得し、CSVに保存する。

    Parameters
    ----------
    version : str
        APIのバージョン番号（例: 'v22.0'）
    ig_user_id : str
        自分のInstagramビジネスアカウントのユーザーID
    user_id : str
        取得対象のInstagramユーザー名
    access_token : str
        Facebook Graph APIのアクセストークン
    today : str
        日付文字列（例: '2026-06-07'）。ファイル名に使用。
    out_dir : str
        CSVの保存先ディレクトリ

    Returns
    -------
    bool
        収集に成功したら True、API制限などで失敗したら False
    """
    # ユーザーIDを使ってビジネスディスカバリー情報の取得
    account_dict = call_business_profile(version, ig_user_id, user_id, access_token)

    # API制限に引っかかった場合の処理　account_dict['error']['code'] == 4となる場合
    try:
        if account_dict["error"]["code"] == 4:
            print(
                "API制限に掛かりました。1時間後にお試しあれ",
                "現在時刻 : ",
                dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            print(f"{user_id} の収集をスキップします。")
            return False
    except Exception:
        pass

    # error キーがあるがコード4以外（ユーザー名誤り・非公開など）の場合もスキップ
    if "business_discovery" not in account_dict and "media.data" not in str(
        account_dict
    ):
        if "error" in account_dict:
            print(f"{user_id} の取得に失敗しました: {account_dict['error']}")
            return False

    # 取得した情報をjson_normalizeで一気にデータフレーム型式に変換
    df_profile = pd.json_normalize(account_dict)
    original_columns = list(df_profile.columns)
    new_columns = []
    for column in original_columns:
        if "business_discovery." in column:
            column = column.replace("business_discovery.", "")
        new_columns.append(column)

    df_profile.columns = new_columns

    # 重複したカラム名があるとデータポータルで読み込めないため、重複しているカラム名idの左側のほうを残して右側は削除
    df_profile = df_profile.loc[:, ~df_profile.columns.duplicated()]
    ensure_dir(out_dir)
    df_profile.to_csv(f"{out_dir}/{user_id}-profile-{today}.csv")

    # メディア情報の取り出し
    media_data = df_profile["media.data"][0]

    # データフレームを作るための空の辞書を作成
    data_dict = make_dict()

    # after_keyがあれば、追加でデータを取得
    after_key = get_after_key(account_dict)

    # after_keyがある場合
    if after_key:
        # 追加でデータを取得する
        pagenate_dict = pagenate(version, ig_user_id, user_id, access_token, after_key)
        pagenate_data = pagenate_dict["business_discovery"]["media"]["data"]

        df1 = make_df(media_data=media_data, data_dict=data_dict)
        df2 = make_df(media_data=pagenate_data, data_dict=data_dict)

        # concatを使って先に作成したデータフレームと結合する
        df = pd.concat([df1, df2])

        # インデックスを振りなおす
        df.reset_index(inplace=True, drop=True)

    # after_keyがない場合　そのままデータフレームを作成
    else:
        print("after_keyがありませんでした。")
        df = make_df(media_data=media_data, data_dict=data_dict)

    df.to_csv(f"{out_dir}/{user_id}_{today}.csv")
    print(f"{user_id} の収集が完了しました。")
    return True



def make_dict() -> dict:
    """
    データフレームのデータを入れるための辞書の作成

    Returns
    -------
    dict
        投稿データを格納する辞書
    """

    # 空の辞書を作成　pd.DataFrame(dict)すればデータフレームが簡単にできる
    data_dict = {}

    # データフレームにするカラム名をキーとして、空のリストで初期化
    key_list = [
        "id",
        "media_type",
        "media_url",
        "caption",
        "hashtag",
        "timestamp",
        "like_count",
        "comments_count",
    ]
    for key in key_list:
        data_dict[key] = []

    return data_dict


def call_business_profile(
    version: str, ig_user_id: str, user_id: str, access_token: str
) -> dict:
    """
    ビジネスディスカバリーでアカウントのプロフィール情報を取得

    Parameters
    ----------
    version : str
        APIのバージョン番号（例: 'v9'）
    ig_user_id : str
        InstagramビジネスアカウントのユーザーID
    user_id : str
        取得対象のユーザーのInstagramユーザー名
    access_token : str
        Facebook Graph APIのアクセストークン

    Returns
    -------
    dict
        指定されたInstagramアカウントのプロフィール情報を含む辞書
    """

    # ビジネスディスカバリーのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){followers_count,media_count,media{comments_count,like_count}}&access_token={access-token}"
    business_api = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{username, website, name, id, profile_picture_url, biography, follows_count, followers_count, media_count, media{{id, timestamp, like_count, comments_count, caption, media_type, media_url, thumbnail_url, video_url}}}}&access_token={access_token}"

    return api_get(business_api)


def get_after_key(account_dict: dict) -> str:
    """
    ページ送りのafter_keyを取得する

    Parameters
    ----------
    account_dict : dict
        指定されたInstagramアカウントのプロフィール情報を含む辞書

    Returns
    -------
    str
        ページ送りのafter_key
    """
    after_key = ""
    # after_keyがある場合
    try:
        after_key = account_dict["business_discovery"]["media"]["paging"]["cursors"][
            "after"
        ]
        return after_key

    # after_keyがない場合
    except KeyError as e:
        print("after_key", e)
        return after_key


def pagenate(
    version: str, ig_user_id: str, user_id: str, access_token: str, after_key: str
) -> dict:
    """
    ユーザー名とafter_keyを受け取り、追加データ分を再度ビジネスディスカバリーでデータを取得する

    Parameters
    ----------
    version : str
        APIのバージョン番号（例: 'v9'）
    ig_user_id : str
        InstagramビジネスアカウントのユーザーID
    user_id : str
        取得対象のユーザーのInstagramユーザー名
    access_token : str
        Facebook Graph APIのアクセストークン
    after_key : str
        ページ送りのafter_key

    Returns
    -------
    dict
        指定されたInstagramアカウントのページ送り後の辞書
    """
    # ビジネスディスカバリーのページ送りのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){media.after(after_key).limit(number)followers_count,media_count,media{comments_count,like_count}}&access_token=access-token"
    api_pagenation = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{media.after({after_key}).limit(1000){{id, timestamp, like_count, comments_count, caption, media_type, media_url, thumbnail_url, video_url}}}}&access_token={access_token}"
    return api_get(api_pagenation)


def make_df(media_data: list, data_dict: dict) -> pd.DataFrame:
    """
    データフレームの作成
    キーがない場合もあるので、try-exceptでエラー処理を記述

    Parameters
    ----------
    media_data : list
        投稿ごとにデータをまとめたlist。listの要素は投稿ごとの辞書。
    data_dict : dict
        データ格納用の辞書フォーマット。

    Returns
    -------
    pd.DataFrame
        投稿内容のデータフレーム、各行に各投稿の内容がまとめてある。
    """
    for media in media_data:
        try:
            caption = media["caption"]

        # たまにキャプションがない場合があるので、その場合の処理を記述
        except KeyError as e:
            caption = ""
            timestamp = media["timestamp"].replace("+0000", "").replace("T", " ")
            print(f"KeyError '{e}'が存在しません。投稿日時：{timestamp}")

        # まず要素を取り出す media_url、caption、hash_tags、timestamp、like_count、comments_count
        media_type = media["media_type"]
        if media_type == "VIDEO":
            media_url = media.get("thumbnail_url", media.get("media_url", None))
        else:
            media_url = media.get("media_url", None)
        hash_tag_list = re.findall("#([^\s→#\ufeff]*)", caption)
        hash_tags = "\n".join(hash_tag_list)
        timestamp = media["timestamp"].replace("+0000", "").replace("T", " ")
        like_count = media.get("like_count", None)
        comments_count = media.get("comments_count", None)
        media_id = media.get("id", None)
        # data_dictの各リストにappendで要素を入れていく
        data_dict["id"].append(media_id)
        data_dict["media_type"].append(media_type)
        data_dict["media_url"].append(media_url)
        data_dict["caption"].append(caption)
        data_dict["hashtag"].append(hash_tags)
        data_dict["timestamp"].append(timestamp)
        data_dict["like_count"].append(like_count)
        data_dict["comments_count"].append(comments_count)
    return pd.DataFrame(data_dict)


if __name__ == "__main__":
    main()
