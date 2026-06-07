# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Instagram投稿データ収集・分析ツール。Facebook Graph API の Business Discovery APIを使って、指定したInstagramアカウントのプロフィール情報・投稿データをCSVに保存する。

## ディレクトリ構成

```
├── src/
│   ├── collect.py       # データ収集スクリプト（メイン）
│   ├── data_loader.py   # CSV読み込み・データ変換ロジック
│   └── dashboard.py     # Streamlit ダッシュボード
├── notebooks/
│   └── plot.ipynb       # フォロワー数の時系列可視化（旧）
├── reference/
│   └── insta-opning.py  # プログラミングスクール配布の元資料（参照用）
├── result/              # 収集済みCSVデータ（.gitignore対象）
├── run.sh               # cron用データ収集スクリプト
├── run_dashboard.sh     # ダッシュボード起動スクリプト
├── requirements.txt     # 依存パッケージ一覧
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

## ダッシュボード

```bash
# ダッシュボード起動（同じWiFi内のスマホからもアクセス可能）
./run_dashboard.sh
```

起動後、ターミナルに表示されるIPアドレス（例: `http://192.168.x.x:8501`）をスマホブラウザで開く。

### ダッシュボードの構成（`src/dashboard.py`）

- **KPIカード** — フォロワー数・30日比・平均エンゲージメント率・投稿数
- **フォロワー推移** — 全期間の折れ線グラフ
- **投稿パフォーマンス一覧** — サムネイル付き、いいね/コメント/エンゲージメント率でソート可
- **エンゲージメント分析** — 時系列散布図・曜日時間帯ヒートマップ・タイプ別比較
- **ハッシュタグ分析** — いいね数が多いタグ・使用頻度ランキング（各TOP20）

### データローダー（`src/data_loader.py`）

- `load_profile_data()` — 全プロフィールCSVをまとめてフォロワー推移データに変換
- `load_media_data()` — 最新メディアCSVを読み込み（UTC→JSTに変換済み）
- `merge_follower_at_post_date()` — 各投稿日のフォロワー数を紐付けてエンゲージメント率を計算

## 注意事項

- API制限（error code 4）に引っかかった場合は1時間後に再実行する
- `result/` と `.env` は `.gitignore` で除外済み
- ダッシュボードのサムネイルはInstagramのCDN URLのため、古い投稿は表示されない場合がある（有効期限あり）
- エンゲージメント率 = (いいね数 + コメント数) / 投稿日時点のフォロワー数 × 100
