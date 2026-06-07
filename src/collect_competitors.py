# 同ジャンルの人気アカウント（競合）を収集するスクリプト
# 既存 collect.py の collect_account() をそのまま再利用する
import os
from datetime import datetime as dt

from dotenv import load_dotenv

from collect import collect_account


def main():
    """
    .env の COMPETITOR_USERNAMES（カンマ区切り）に列挙したアカウントを
    Business Discovery API で収集し、result/competitors/ 配下に保存する。
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))

    access_token = os.getenv("ACCESS_TOKEN")
    version = os.getenv("VERSION")
    ig_user_id = os.getenv("IG_USER_ID")

    raw = os.getenv("COMPETITOR_USERNAMES", "")
    competitors = [u.strip() for u in raw.split(",") if u.strip()]

    if not competitors:
        print(
            "COMPETITOR_USERNAMES が .env に設定されていません。"
            "（例: COMPETITOR_USERNAMES=acc1,acc2,acc3）"
        )
        return

    today = dt.now().strftime("%Y-%m-%d")
    out_dir = os.path.join(base_dir, "result", "competitors")

    print(f"競合 {len(competitors)} 件を収集します: {competitors}")
    for username in competitors:
        collect_account(version, ig_user_id, username, access_token, today, out_dir)


if __name__ == "__main__":
    main()
