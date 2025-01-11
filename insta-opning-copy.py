# 必要なモジュールをimport
import requests
import json
import pandas as pd
import os
import sys
import re
from datetime import datetime as dt
from dotenv import load_dotenv
from pprint import pprint


def main():
    """
    メイン関数
    """

    # .envファイルからトークン情報などの取得
    load_dotenv()

    # os.environ.getまたはos.getenvを使用してenvファイルからトークン情報の読み込み
    access_token = os.getenv("ACCESS_TOKEN")
    version = os.getenv("VERSION")
    ig_user_id = os.getenv("IG_USER_ID")

    # ユーザーIDを入力
    user_id = "moriyamakaede"

    # 今日の日付を取得　文字列で年-月-日の型式にする
    today = dt.now().strftime("%Y-%m-%d")

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
            print("プログラムを終了します。")
            sys.exit()
    except Exception:
        pass
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
    path = "./result"
    make_result_dirs(path)
    df_profile.to_csv(f"{path}/{user_id}-profile-{today}.csv")

    # メディア情報の取り出し
    media_data = df_profile["media.data"][0]
    # pprint(media_data[3].keys())

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

    # 結果csv保存用のディレクトリ作成
    path = "./result"
    make_result_dirs(path)
    df.to_csv(f"{path}/{user_id}_{today}.csv")


def make_result_dirs(path):
    """
    結果データ保存のためのディレクトリ作成

    Parameters
    ----------
    path : str
        結果データ保存のためのディレクトリのパス名
    """
    if not os.path.isdir(path):
        os.makedirs(path)


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
        "media_type",
        "media_url",
        "caption",
        "hashtag",
        "timestamp",
        "like_count",
        "comments_count",
        # "id",
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
    business_api = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{username, website, name, id, profile_picture_url, biography, follows_count, followers_count, media_count, media{{timestamp, like_count, comments_count, caption, media_type, media_url, thumbnail_url, video_url}}}}&access_token={access_token}"

    # GETリクエスト
    r = requests.get(business_api)

    # JSON文字列を辞書に変換
    account_dict = json.loads(r.content)
    return account_dict


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
    api_pagenation = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{media.after({after_key}).limit(1000){{timestamp, like_count, comments_count, caption, media_type, media_url, thumbnail_url,video_url}}}}&access_token={access_token}"
    # GETリクエスト
    r = requests.get(api_pagenation)

    # JSON文字列を辞書に変換
    account_dict = json.loads(r.content)
    return account_dict


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
            media_url = media["thumbnail_url"]
        else:
            media_url = media["media_url"]
        hash_tag_list = re.findall("#([^\s→#\ufeff]*)", caption)
        hash_tags = "\n".join(hash_tag_list)
        timestamp = media["timestamp"].replace("+0000", "").replace("T", " ")
        like_count = media["like_count"]
        comments_count = media["comments_count"]
        # data_dictの各リストにappendで要素を入れていく
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
