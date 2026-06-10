# 同ジャンルの人気アカウント（競合）を収集するスクリプト
# 既存 collect.py の collect_account() をそのまま再利用する
import os

from collect import collect_account
from collect_utils import ensure_dir, load_env, today_str


def main():
    """
    .env の COMPETITOR_USERNAMES（カンマ区切り）に列挙したアカウントを
    Business Discovery API で収集し、result/competitors/ 配下に保存する。
    """
    env = load_env()

    raw = os.getenv("COMPETITOR_USERNAMES", "")
    competitors = [u.strip() for u in raw.split(",") if u.strip()]

    if not competitors:
        print(
            "COMPETITOR_USERNAMES が .env に設定されていません。"
            "（例: COMPETITOR_USERNAMES=acc1,acc2,acc3）"
        )
        return

    out_dir = os.path.join(env.base_dir, "result", "competitors")
    ensure_dir(out_dir)

    print(f"競合 {len(competitors)} 件を収集します: {competitors}")
    for username in competitors:
        collect_account(env.version, env.ig_user_id, username, env.access_token, today_str(), out_dir)


if __name__ == "__main__":
    main()
