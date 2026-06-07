# Instagram Analyzer

Facebook Graph API（Business Discovery API）を使って、指定したInstagramアカウントのデータを収集・分析するツール。

## 機能

- プロフィール情報の取得（フォロワー数・フォロー数・投稿数）
- 投稿データの取得（いいね数・コメント数・ハッシュタグ・メディアタイプ）
- cronによる毎日0時の自動収集

## セットアップ

```bash
git clone https://github.com/taru-boy/instagram_analize.git
cd instagram_analize
python -m venv .venv
source .venv/bin/activate
pip install requests pandas python-dotenv
```

`.env` ファイルをプロジェクトルートに作成：

```
ACCESS_TOKEN=your_facebook_graph_api_token
VERSION=v22.0
IG_USER_ID=your_instagram_business_account_id
TARGET_USER_ID=target_instagram_username
```

## 使い方

```bash
python src/collect.py
```

`result/` ディレクトリに以下のCSVが保存されます：

| ファイル | 内容 |
|---|---|
| `{user_id}-profile-{date}.csv` | プロフィール情報 |
| `{user_id}_{date}.csv` | 投稿データ一覧 |

## cron設定（毎日0時に自動実行）

```bash
chmod +x run.sh
crontab -e
# 以下を追加
00 00 * * * /path/to/instagram_analize/run.sh
```

実行ログは `logs/collect.log` に出力されます。

## 必要なもの

- Facebook開発者アカウント
- InstagramビジネスアカウントのGraph APIアクセストークン
