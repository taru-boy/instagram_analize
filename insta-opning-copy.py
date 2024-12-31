# 必要なモジュールをimport
import requests
import json
import pandas as pd
import os
import sys
import re

"""
メイン関数
"""

# .envファイルからトークン情報などの取得

# os.environ.getまたはos.getenvを使用してenvファイルからトークン情報の読み込み

# ユーザーIDを入力

# 今日の日付を取得　文字列で年-月-日の型式にする

# ユーザーIDを使ってビジネスディスカバリー情報の取得

# API制限に引っかかった場合の処理　account_dict['error']['code'] == 4となる場合

# 取得した情報をjson_normalizeで一気にデータフレーム型式に変換

# 重複したカラム名があるとデータポータルで読み込めないため、重複しているカラム名idの左側のほうを残して右側は削除

# メディア情報の取り出し

# データフレームを作るための空の辞書を作成

# after_keyがあれば、追加でデータを取得

# after_keyがある場合

# 追加でデータを取得する

# concatを使って先に作成したデータフレームと結合する

# インデックスを振りなおす

# 結果csv保存用のディレクトリ作成

# after_keyがない場合　そのままデータフレームを作成

"""
結果データ保存のための
ディレクトリ作成
"""

"""
データフレームのデータを
入れるための辞書の作成
"""

# 空の辞書を作成　pd.DataFrame(dict)すればデータフレームが簡単にできる

# データフレームにするカラム名をキーとして、空のリストで初期化

"""
ビジネスディスカバリーで
アカウントのプロフィール情報を取得
"""

# ビジネスディスカバリーのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){followers_count,media_count,media{comments_count,like_count}}&access_token={access-token}"

# GETリクエスト

# JSON文字列を辞書に変換

"""
ページ送りのafter_keyを取得する
"""

# after_keyがある場合

# after_keyがない場合

"""
ユーザー名とafter_keyを受け取り、追加データ分を
再度ビジネスディスカバリーでデータを取得する
"""
# ビジネスディスカバリーのページ送りのエンドポイントの設定　"https://graph.facebook.com/v9/ig_user_id?fields=business_discovery.username(user_id)){media.after(after_key).limit(number)followers_count,media_count,media{comments_count,like_count}}&access_token=access-token"

# JSON文字列を辞書に変換

"""
データフレームの作成
キーがない場合もあるので、
try-exceptでエラー処理を記述
"""

# まず要素を取り出す media_url、caption、hash_tags、timestamp、like_count、comments_count

# data_dictの各リストにappendで要素を入れていく

# たまにキーがない場合があるので、その場合の処理を記述

# まず要素を取り出す media_url、caption、hash_tags、timestamp、like_count、comments_count

# data_dictの各リストにappendで要素を入れていく
