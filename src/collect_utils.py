"""
collect 系スクリプト共通ユーティリティ。

環境変数読み込み・Graph API GET・ディレクトリ作成・日付文字列生成の
重複コードを集約する。各 collect_*.py の main() から利用する。
"""

import json
import os
from collections import namedtuple
from datetime import datetime as dt

import requests
from dotenv import load_dotenv

Env = namedtuple("Env", "base_dir access_token version ig_user_id target_user_id")


def load_env() -> Env:
    """プロジェクトルートの .env を読み込み認証情報を返す。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))
    return Env(
        base_dir=base_dir,
        access_token=os.getenv("ACCESS_TOKEN"),
        version=os.getenv("VERSION"),
        ig_user_id=os.getenv("IG_USER_ID"),
        target_user_id=os.getenv("TARGET_USER_ID"),
    )


def api_get(url: str) -> dict:
    """Graph API を GET して JSON を dict で返す。"""
    r = requests.get(url)
    return json.loads(r.content)


def today_str() -> str:
    """今日の日付を 'YYYY-MM-DD' 形式の文字列で返す。"""
    return dt.now().strftime("%Y-%m-%d")


def ensure_dir(path: str) -> None:
    """ディレクトリが無ければ作成する。"""
    os.makedirs(path, exist_ok=True)
