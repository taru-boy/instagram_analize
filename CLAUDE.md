# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Instagram投稿データ収集・分析ツール。Facebook Graph API の Business Discovery APIを使って、指定したInstagramアカウントのプロフィール情報・投稿データをCSVに保存する。さらに競合アカウント・ハッシュタグ人気投稿のトレンドを集め、統計＋Claude AIで「次の投稿案」を提案する。

**重要：`ACCESS_TOKEN`/`IG_USER_ID` は妻のアカウント本体のトークン。** そのため Business Discovery 経由（like/commentのみ）に加え、インサイト系エンドポイント（`/{media-id}/insights`、`/{ig-user-id}/insights`）を直接叩いてリーチ・保存・シェア・プロフィールアクセス・リンククリックも取得できる（`collect_insights.py`）。

## ディレクトリ構成

```
├── src/
│   ├── collect.py             # データ収集スクリプト（メイン。collect_account()を共有）
│   ├── collect_insights.py    # インサイト収集（リーチ・保存・シェア・プロフィールアクセス等）
│   ├── collect_competitors.py # 競合アカウント収集（collect.pyの関数を再利用）
│   ├── collect_hashtags.py    # ハッシュタグ人気投稿収集（IG Hashtag Search）
│   ├── data_loader.py         # CSV読み込み・データ変換ロジック
│   ├── insights.py            # 統計ベースの「伸びる条件」抽出（純関数）
│   ├── suggest.py             # Claude AIによる投稿案生成（構造化出力）
│   └── dashboard.py           # Streamlit ダッシュボード
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

`.env` に以下が必要：

```
ACCESS_TOKEN=...                    # Facebook Graph API アクセストークン
VERSION=v22.0                       # Graph API バージョン
IG_USER_ID=...                      # 自分のInstagramビジネスアカウントのID
TARGET_USER_ID=...                  # 分析対象（妻）のInstagramユーザー名

# --- 投稿提案機能で使用 ---
ANTHROPIC_API_KEY=...               # Claude API キー（投稿案生成に必要）
COMPETITOR_USERNAMES=acc1,acc2      # 競合アカウント（カンマ区切り）
TREND_HASHTAGS=水彩画,イラスト,アート  # トレンド収集タグ（カンマ区切り。5〜10個推奨）
```

## 実行

```bash
# プロジェクトルートから実行
python src/collect.py              # 妻アカウントの収集
python src/collect_insights.py     # インサイト収集（直近200件。--all で全件、--limit Nで件数指定）
python src/collect_competitors.py  # 競合アカウントの収集
python src/collect_hashtags.py     # ハッシュタグ人気投稿の収集
```

実行すると `result/` 配下にCSVが保存される：
- `{TARGET_USER_ID}-profile-{today}.csv` — プロフィール情報（フォロワー数・フォロー数・投稿数など）
- `{TARGET_USER_ID}_{today}.csv` — 投稿一覧（**id**・メディアURL・キャプション・ハッシュタグ・いいね数・コメント数・メディアタイプ）
- `insights/{IG_USER_ID}_media_insights_{today}.csv` — 投稿ID別インサイト（reach/saved/shares/total_interactions/profile_visits/views）
- `insights/{IG_USER_ID}_account_insights_{today}.csv` — アカウント日次インサイト（profile_views/website_clicks/reach/accounts_engaged）
- `competitors/{username}-profile-{today}.csv` / `competitors/{username}_{today}.csv` — 競合のプロフィール・投稿
- `hashtags/{tag}_{today}.csv` — タグ別の人気投稿（top_media）
- `suggestions/{today}.json` — AI生成の投稿案キャッシュ（同日は再課金しない）

## アーキテクチャ

### データ取得フロー（`src/collect.py`）

1. `call_business_profile()` — 初回リクエスト（最大25件程度のメディアデータ含む）
2. `get_after_key()` — レスポンスからカーソルを取得
3. `pagenate()` — after_keyがあれば追加リクエストで残り全件取得（上限1000件）
4. `make_df()` — リスト形式のメディアデータをDataFrameに変換。VIDEO投稿は `thumbnail_url` を使用。
5. `collect_account()` — 上記をまとめた1アカウント分の収集処理。`collect.py` 本体と `collect_competitors.py` が共有する。

### インサイト収集（`src/collect_insights.py`）

- **Business Discovery では取れない指標**（リーチ・保存・シェア・プロフィールアクセス・リンククリック）を、
  妻アカウント本体のトークンで直接取得する。新しい環境変数・権限は不要（既存トークンに `instagram_manage_insights` あり）。
- `fetch_media_list()` — `/{IG_USER_ID}/media` をページネーションして全メディアID＋タイプを取得。
- `fetch_media_insights()` — `/{media-id}/insights` を叩く。**メディアタイプで metric を分岐**
  （IMAGE/CAROUSEL: reach,saved,shares,total_interactions,profile_visits ／ VIDEO/REELS: …+views）。
  タイプ非対応の `#100` エラー時は CORE_METRICS（reach,saved,shares）でフォールバック。
- `fetch_account_insights()` — `/{IG_USER_ID}/insights?...&metric_type=total_value` でアカウント日次インサイト。
- レート制限対策：デフォルトは直近200件のみ。`--all` で全件、`--limit N` で件数指定、`--sleep` でウェイト調整。

### トレンド収集

- `collect_competitors.py` — `COMPETITOR_USERNAMES` の各アカウントを `collect_account()` で収集。
- `collect_hashtags.py` — `ig_hashtag_search` でタグIDを取得 → `{hashtag_id}/top_media` で人気投稿を取得。
  **API制限: 1アカウントにつき7日間で30ユニークタグまで／200req毎時。** タグ数は絞り、cronは週1〜2回に。

### 投稿提案（`src/insights.py` + `src/suggest.py`）

- `insights.py` — 統計ベースの純関数群（AI不使用・無料）。
  `best_posting_slots()`（最適な曜日×時間）・`best_media_type()`・`top_hashtags_by_engagement()`・
  `trending_topics()`（競合/タグから集計）・`caption_length_analysis()`（最適なキャプション長）・
  `hashtag_count_analysis()`（最適なタグ個数。0個推奨は避ける`best_actionable_band`を提供）・
  `posting_cadence()`（投稿ペース・傾向）・`low_performers()`（避けたい条件）・
  `competitor_gap()`（競合が多用＆未使用のタグ／エンゲージ比較）・
  `actionable_advice()`（★上記を総合したルールベースの日本語「次にやるべきこと」助言）・
  `build_summary()`（一括）。
- `suggest.py` — 統計サマリ＋高エンゲージ投稿例＋トレンドをプロンプト化し、`claude-opus-4-8` に
  構造化出力（`messages.parse()` + Pydantic）でリクエスト。投稿案3〜5件（テーマ・キャプション案・
  タグ・タイプ・推奨時間・根拠・予測エンゲージメント）を生成。結果は `result/suggestions/{today}.json`
  にキャッシュ（同日は再課金しない）。`generate_suggestions(force=True)` で再生成。

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
- **インサイトKPI**（インサイト取得時のみ）— 平均リーチ・平均保存数・平均シェア数・直近プロフィールアクセス（+リンククリック）
- **フォロワー推移** — 全期間の折れ線グラフ
- **投稿パフォーマンス一覧** — サムネイル付き、いいね/コメント/エンゲージメント率/リーチ/保存/シェアでソート可。インサイトがあればカードに👀リーチ・🔖保存・🔁シェア・▶️再生数も表示
- **エンゲージメント分析** — 時系列散布図・曜日時間帯ヒートマップ・タイプ別比較
- **リーチ・保存分析**（インサイト取得時のみ）— リーチ推移・保存率ランキングTOP10・タイプ別リーチ/保存
- **ハッシュタグ分析** — いいね数が多いタグ・使用頻度ランキング（各TOP20）
- **投稿提案** — ①「📋 次にやるべきこと」（統計から自動生成の助言・無料）②「伸びる条件」カード
  （最適タイミング・伸びるタイプ・効くタグ・業界トレンド）③「伸びる投稿の型」（最適キャプション長・
  タグ数・投稿ペースとグラフ）④「避けたい条件」⑤「競合から学ぶ」⑥ボタンで起動するAI投稿案
  （任意・`st.session_state` にキャッシュし連打課金を防止）

### データローダー（`src/data_loader.py`）

- `load_profile_data()` — 全プロフィールCSVをまとめてフォロワー推移データに変換
- `load_media_data()` — 最新メディアCSVを読み込み（UTC→JSTに変換済み）
- `merge_follower_at_post_date()` — 各投稿日のフォロワー数を紐付けてエンゲージメント率を計算
- `load_insights_data()` — `result/insights/` の**全**メディア別インサイトCSVを統合し、`id` ごとに最新の非欠損値を採用（日次で直近N件のみ収集しても、過去 `--all` で取得した全履歴のカバレッジが失われない。`groupby.last()` を利用）
- `load_account_insights_data()` — `result/insights/` の全アカウント別インサイトCSVを日次推移として結合
- `merge_insights()` — メディアデータに `id` でインサイト列を結合。保存率 `saved_rate`・リーチベースのエンゲージ率 `reach_engagement_rate` を算出
- `load_competitor_data()` — `result/competitors/` の各競合の最新メディアCSVを結合（`competitor`列付き）
- `load_hashtag_data()` — `result/hashtags/` の各タグの最新CSVを結合（`search_hashtag`列付き）

## 注意事項

- API制限（error code 4）に引っかかった場合は1時間後に再実行する
- ハッシュタグ収集は「7日間で30ユニークタグまで」。`TREND_HASHTAGS` は絞り、頻度を抑える
- ハッシュタグの top_media では投稿者のフォロワー数・ユーザー名は取得できない（いいね/コメント/キャプション/タイプは取得可）
- `result/` と `.env` は `.gitignore` で除外済み
- ダッシュボードのサムネイルはInstagramのCDN URLのため、古い投稿は表示されない場合がある（有効期限あり）
- エンゲージメント率 = (いいね数 + コメント数) / 投稿日時点のフォロワー数 × 100
- AI投稿案は `claude-opus-4-8` を使用。生成1回ごとに少額課金が発生（同日キャッシュで再課金回避）
- インサイトとメディアCSVは `id` で結合する。`id` 列はある時点から追加されたため、それ以前のメディアCSVには `id` が無くインサイトが結合できない（`collect.py` を再実行すれば最新CSVに `id` が付与される）
- `profile_visits`（投稿経由のプロフィール訪問）と `profile_views`（アカウント全体のプロフィールアクセス）は別物
- アカウントインサイトは `period=day`（当日分のみ）。推移を見るには日次cron（`run.sh`）で毎日蓄積する
- インサイトAPIにもレート制限（200req/h）あり。`collect_insights.py` はデフォルトで直近200件のみ取得
- APIバージョンは v22.0。欲しいインサイト指標は v22 で全取得可能（バージョンアップは任意）。`impressions`・非Reelsの`video_views` は2025年に廃止済み（→`reach`・`views`で代替）
