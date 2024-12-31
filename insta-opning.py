# 必要なモジュールをimport
import requests
import json
import pandas as pd
import os
import sys
import re
from datetime import datetime as dt
from dotenv import load_dotenv


def main():
    """
    メイン関数
    """
    # .envファイルからトークン情報などの取得
    load_dotenv()
    # os.environ.getまたはos.getenvを使用してenvファイルからトークン情報の読み込み
    access_token = os.environ.get("ACCESS_TOKEN")
    version = os.environ.get("VERSION")
    ig_user_id = os.environ.get("IG_USER_ID")
    # ユーザーIDを入力
    user_id = "mr.cheesecake.tokyo"
    # 今日の日付を取得　文字列で年-月-日の型式にする
    today = dt.now().strftime("%Y-%m-%d")
    # ユーザーIDを使ってビジネスディスカバリー情報の取得
    account_dict = call_bussiness_profile(version, ig_user_id, user_id, access_token)
    # 取得した情報をjson_normalizeで一気にデータフレーム型式に変換
    df1 = pd.json_normalize(account_dict)
    df1.rename(
        columns={
            "business_discovery.username": "username",
            "business_discovery.website": "website",
            "business_discovery.name": "name",
            "business_discovery.id": "id",
            "business_discovery.profile_picture_url": "profile_picture_url",
            "business_discovery.biography": "biography",
            "business_discovery.follows_count": "follows_count",
            "business_discovery.followers_count": "followers_count",
            "business_discovery.media_count": "media_count",
        },
        inplace=True,
    )
    # 重複したカラム名があるとデータポータルで読み込めないため、重複しているカラム名idの左側のほうを残して右側は削除
    df1 = df1.loc[:, ~df1.columns.duplicated()]
    df1.to_csv(f"./result/{user_id}-profile-{today}.csv")
    # API制限に引っかかった場合の処理　account_dict['error']['code'] == 4となる場合
    try:
        if account_dict["error"]["code"] == 4:
            print(
                "APIリミットに達しました。1時間後に再度試してみて下さい。",
                "現在時刻:",
                dt.now().strftime("%Y/%m/%d %H:%M:%S"),
            )
            print("プログラムを終了します。")
            sys.exit()
    except Exception:
        pass

    media_data = df1["business_discovery.media.data"][0]
    data_dict = make_dict()

    # after_keyがあれば、追加でデータを取得
    after_key = after_key_get(account_dict)
    # after_keyがある場合
    if after_key:
        # 追加でデータを取得する
        pagenate_dict = pagenate(user_id, after_key, version, ig_user_id, access_token)
        pagenate_data = pagenate_dict["business_discovery"]["media"]["data"]
        # 先に作成したデータフレームと結合する
        df1 = make_data_df(media_data, data_dict)
        df2 = make_data_df(pagenate_data, data_dict)
        df = pd.concat([df1, df2])
        # インデックスを振りなおす
        df.reset_index(inplace=True, drop=True)
        # 結果csv保存用のディレクトリ作成
        my_makedirs("./result")
        df.to_csv(f"./result/{user_id}-{today}.csv")
    else:
        # after_keyがない場合　そのままデータフレームを作成
        print("after_keyがありませんでした。")
        df = make_data_df(media_data, data_dict)
        my_makedirs("./result")
        df.to_csv(f"./result/{user_id}-{today}.csv")


def my_makedirs(path):
    """
    結果データ保存のための
    ディレクトリ作成
    """
    if not os.path.isdir(path):
        os.makedirs(path)


def make_dict():
    """
    データフレームのデータを
    入れるための辞書の作成
    """
    # 空の辞書を作成　pd.DataFrame(dict)すればデータフレームが簡単にできる
    data_dict = {}
    # データフレームにするカラム名をキーとして、空のリストで初期化
    data_dict["media_url"] = []
    data_dict["caption"] = []
    data_dict["hashtag"] = []
    data_dict["timestamp"] = []
    data_dict["like_count"] = []
    data_dict["comments_count"] = []
    return data_dict


def call_bussiness_profile(version, ig_user_id, user_id, access_token):
    """
    ビジネスディスカバリーで
    アカウントのプロフィール情報を取得
    """
    # ビジネスディスカバリーのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){followers_count,media_count,media{comments_count,like_count}}&access_token={access-token}"
    bussiness_api = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{username, website, name, id, profile_picture_url, biography, follows_count,followers_count, media_count, media{{timestamp, like_count, comments_count, caption, media_url}}}}&access_token={access_token}"
    # GETリクエスト
    r = requests.get(bussiness_api)
    # JSON文字列を辞書に変換
    account_dict = json.loads(r.content)
    return account_dict


def after_key_get(account_dict):
    """
    ページ送りのafter_keyを取得する
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


def pagenate(user_id, after_key, version, ig_user_id, access_token):
    """
    ユーザー名とafter_keyを受け取り、追加データ分を
    再度ビジネスディスカバリーでデータを取得する
    """
    # ビジネスディスカバリーのページ送りのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){media.after(after_key).limit(number)followers_count,media_count,media{comments_count,like_count}}&access_token=access-token"
    api_pagenation = f"https://graph.facebook.com/{version}/{ig_user_id}?fields=business_discovery.username({user_id}){{media.after({after_key}).limit(300){{timestamp, like_count, comments_count, caption, media_url}}}}&access_token={access_token}"
    r = requests.get(api_pagenation)
    pagenate_dict = json.loads(r.content)

    return pagenate_dict


def make_data_df(media_data, data_dict):
    """
    データフレームの作成
    キーがない場合もあるので、
    try-exceptでエラー処理を記述
    """
    for i in range(len(media_data)):
        try:
            # まず要素を取り出す media_url、caption、hash_tags、timestamp、like_count、comments_count
            media_url = media_data[i]["media_url"]
            caption = media_data[i]["caption"]
            hash_tag_list = re.findall("#([^\s→#\ufeff]*)", caption)
            hash_tags = "\n".join(hash_tag_list)
            timestamp = (
                media_data[i]["timestamp"].replace("+0000", "").replace("T", " ")
            )
            like_count = media_data[i]["like_count"]
            comments_count = media_data[i]["comments_count"]
            # data_dictの各リストにappendで要素を入れていく
            data_dict["media_url"].append(media_url)
            data_dict["caption"].append(caption)
            data_dict["hashtag"].append(hash_tags)
            data_dict["timestamp"].append(timestamp)
            data_dict["like_count"].append(like_count)
            data_dict["comments_count"].append(comments_count)
            # たまにキーがない場合があるので、その場合の処理を記述
        except KeyError as e:
            print("KeyError", e, "というKeyが存在しません")
            media_url = media_data[i]["media_url"]
            caption = ""
            hash_tags = ""
            timestamp = (
                media_data[i]["timestamp"].replace("+0000", "").replace("T", " ")
            )
            like_count = media_data[i]["like_count"]
            comments_count = media_data[i]["comments_count"]
            data_dict["media_url"].append(media_url)
            data_dict["caption"].append(caption)
            data_dict["hashtag"].append(hash_tags)
            data_dict["timestamp"].append(timestamp)
            data_dict["like_count"].append(like_count)
            data_dict["comments_count"].append(comments_count)
    return pd.DataFrame(data_dict)


if __name__ == "__main__":
    main()
