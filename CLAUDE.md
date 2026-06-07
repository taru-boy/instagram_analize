# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Instagram投稿データ収集・分析ツール。Facebook Graph API の Business Discovery APIを使って、指定したInstagramアカウントのプロフィール情報・投稿データをCSVに保存する。

## ディレクトリ構成

```
├── src/
│   └── collect.py       # データ収集スクリプト（メイン）
├── notebooks/
│   └── plot.ipynb       # フォロワー数の時系列可視化
├── reference/
│   └── insta-opning.py  # プログラミングスクール配布の元資料（参照用）
├── result/              # 収集済みCSVデータ（.gitignore対象）
├── .env                 # APIトークン（.gitignore対象）
└── CLAUDE.md
```

## セットアップ

```bash
source .venv/bin/activate
```

`.env` に以下の3変数が必要：

```
ACCESS_TOKEN=...   # Facebook Graph API アクセストークン
VERSION=v22.0      # Graph API バージョン
IG_USER_ID=...     # 自分のInstagramビジネスアカウントのID
```

## 実行

```bash
# プロジェクトルートから実行
python src/collect.py
```

実行すると `result/` に2種類のCSVが保存される：
- `{TARGET_USER_ID}-profile-{today}.csv` — プロフィール情報（フォロワー数・フォロー数・投稿数など）
- `{TARGET_USER_ID}_{today}.csv` — 投稿一覧（メディアURL・キャプション・ハッシュタグ・いいね数・コメント数・メディアタイプ）

## アーキテクチャ

### データ取得フロー（`src/collect.py`）

1. `call_business_profile()` — 初回リクエスト（最大25件程度のメディアデータ含む）
2. `get_after_key()` — レスポンスからカーソルを取得
3. `pagenate()` — after_keyがあれば追加リクエストで残り全件取得（上限1000件）
4. `make_df()` — リスト形式のメディアデータをDataFrameに変換。VIDEO投稿は `thumbnail_url` を使用。

### 可視化（`notebooks/plot.ipynb`）

`result/` 内の `-profile-` CSVを全件読み込み、フォロワー数の時系列グラフを描画。

## 注意事項

- API制限（error code 4）に引っかかった場合は1時間後に再実行する
- `result/` と `.env` は `.gitignore` で除外済み
