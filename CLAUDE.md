# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Instagram投稿データ収集・分析ツール。Facebook Graph API の Business Discovery API を使って、指定したInstagramアカウントのプロフィール情報・投稿データをCSVに保存する。さらに競合アカウント・ハッシュタグ人気投稿のトレンドを集め、統計＋Claude AIで「次の投稿案」を提案する。

**重要：`ACCESS_TOKEN`／`IG_USER_ID` は妻のアカウント本体のトークン。** Business Discovery ではいいね・コメントしか取れないが、本体トークンならインサイト系エンドポイント（`/{media-id}/insights`、`/{ig-user-id}/insights`）を直接叩けるため、リーチ・保存・シェア・プロフィールアクセス・リンククリックも取得できる（`collect_insights.py`）。

## ディレクトリ構成

```
├── src/
│   ├── collect.py             # データ収集スクリプト（メイン。collect_account()を共有）
│   ├── collect_insights.py    # インサイト収集（リーチ・保存・シェア・プロフィールアクセス等）
│   ├── collect_visual.py      # 投稿画像の軽量視覚特徴収集（色・明るさ・余白・描き込み量等。API課金なし）
│   ├── collect_competitors.py # 競合アカウント収集（collect.pyの関数を再利用）
│   ├── collect_hashtags.py    # ハッシュタグ人気投稿収集（IG Hashtag Search）
│   ├── collect_utils.py       # collect系共通ユーティリティ（env読み込み・api_get・ensure_dir）
│   ├── data_loader.py         # CSV読み込み・データ変換ロジック
│   ├── insights.py            # 統計ベースの「伸びる条件」抽出（純関数）
│   ├── suggest.py             # Claude AIによる投稿案生成（構造化出力）
│   └── dashboard.py           # Streamlit ダッシュボード
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
python src/collect_insights.py     # インサイト収集（直近200件。--all で全件、--limit Nで件数指定、--no-breakdown でフォロワー外リーチ分解を省略）
python src/collect_visual.py       # 投稿画像の視覚特徴収集（直近200件のうち未処理。--all で全件、--limit Nで件数指定、--force で再計算）
python src/collect_competitors.py  # 競合アカウントの収集
python src/collect_hashtags.py     # ハッシュタグ人気投稿の収集
```

実行すると `result/` 配下にCSVが保存される：
- `{TARGET_USER_ID}-profile-{today}.csv` — プロフィール情報（フォロワー数・フォロー数・投稿数など）
- `{TARGET_USER_ID}_{today}.csv` — 投稿一覧（**id**・メディアURL・キャプション・ハッシュタグ・いいね数・コメント数・メディアタイプ）
- `insights/{IG_USER_ID}_media_insights_{today}.csv` — 投稿ID別インサイト（reach/saved/shares/total_interactions/profile_visits/views）。
  **注: `reach_follower`／`reach_non_follower` の列はあるが常に空。メディア単位の follower_type 分解は v22.0 で非対応（`#100 Incompatible breakdowns`）。フォロワー外リーチはアカウント日次インサイトでのみ取得できる。**
- `insights/{IG_USER_ID}_account_insights_{today}.csv` — アカウント日次インサイト（profile_views/website_clicks/reach/accounts_engaged/**reach_follower/reach_non_follower**）
- `visual/{TARGET_USER_ID}_visual_{today}.csv` — 投稿ID別の視覚特徴（brightness/saturation/contrast/colorfulness/warm_ratio/**dominant_color**/whitespace_ratio/edge_density/palette_size/sharpness）。画像ファイルは保存せず数値特徴のみキャッシュ
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
- `_request_reach_breakdown()` — **フォロワー外リーチ**（発見＝新規との出会いの指標）を取得。`reach` を
  `breakdown=follow_type&metric_type=total_value` で分解し `reach_follower`／`reach_non_follower` を得る。
  他メトリックと混在できないため reach 専用の追加リクエストとして発行。
  **アカウントレベル（`/{ig-user-id}/insights`・`period=day` 必須）専用。メディア単位は v22.0 で非対応（`#100`）なので
  `fetch_media_insights` は breakdown を発行せず、`with_breakdown` 引数は実質no-op（媒体別 reach_non_follower は常に欠損）。**
  非対応・エラー時は None で握りつぶす。`--no-breakdown` でアカウント側の分解も省略可。
- `fetch_account_insights()` — `/{IG_USER_ID}/insights?...&metric_type=total_value` でアカウント日次インサイト。
  当日 reach の follower_type 分解（`period=day`）もマージする。**フォロワー外リーチが実際に貯まるのはここだけ**なので、
  推移を見るには日次cron（`run.sh`）の継続が必須。
- レート制限対策：デフォルトは直近200件のみ。`--all` で全件、`--limit N` で件数指定、`--sleep` でウェイト調整。
  breakdown のリクエストはアカウント側の1回のみ（メディア1件あたりは常に1リクエスト）。

### 視覚特徴収集（`src/collect_visual.py`）

- **「写真そのもの」をローカルで数値化**する（Claude/API は使わず課金なし）。画家＝作品販売アカウントでは
  色・明るさ・余白・描き込み量といった見た目が保存率/リーチを左右するため、`id` ごとに特徴を抽出する。
- `load_media_data()`（data_loader）で `id`＋`media_url` を取得 → 各画像を `requests` で**メモリにDL**し、
  PIL で長辺200pxに縮小、numpy で特徴算出。**画像ファイルは保存せず**、抽出後の数値特徴のみ CSV にキャッシュ。
- `extract_features()` — 計10特徴を返す。色・明るさ系（brightness/saturation/contrast/colorfulness/
  warm_ratio/dominant_color）＋構造・質感系（whitespace_ratio＝余白率／edge_density＝描き込み量／
  palette_size＝色数／sharpness＝ラプラシアン分散）。`_rgb_to_hsv()` は vectorized 変換。
- 既に特徴を持つ `id` はスキップ（増分実行。`_existing_done_ids()`）。`--force` で再計算。
  同日に複数回実行した場合は既存ファイルと結合して `id` 重複を除く。
- **IG の CDN URL は期限切れで取得不能**になるため、取れるうちに蓄積する設計（取得失敗は欠損のままスキップ）。
  デフォルトは直近200件のうち未処理のみ。`--all`／`--limit N`／`--sleep` あり。

### トレンド収集

- `collect_competitors.py` — `COMPETITOR_USERNAMES` の各アカウントを `collect_account()` で収集。
- `collect_hashtags.py` — `ig_hashtag_search` でタグIDを取得し、`{hashtag_id}/top_media` で人気投稿を取得。
  **API制限: 1アカウントにつき7日間で30ユニークタグまで／毎時200リクエストまで。** タグ数は絞り、cronは週1〜2回に抑える。

### 投稿提案（`src/insights.py` + `src/suggest.py`）

- `insights.py` — 統計ベースの純関数群（AI不使用・無料）。
  `best_posting_slots()`（最適な曜日×時間）・`best_media_type()`・`top_hashtags_by_engagement()`・
  `trending_topics()`（競合/タグから集計）・`caption_length_analysis()`（最適なキャプション長）・
  `hashtag_count_analysis()`（最適なタグ個数。0個推奨は避ける`best_actionable_band`を提供）・
  `posting_cadence()`（投稿ペース・傾向）・`low_performers()`（避けたい条件）・
  `competitor_gap()`（競合が多用＆未使用のタグ／エンゲージ比較）・
  `visual_engagement_analysis()`（★視覚特徴×エンゲージ。指標は**調整保存率 `saved_rate_adj` 優先**→生保存率→ER→いいねにフォールバック。
  連続特徴は5分位（最低/低/中/高/最高）の帯別平均、`dominant_color` はカテゴリ別平均をランキング。`_quantile_engagement()`・
  `_visual_engagement_col()` を使用。視覚特徴が無ければ空dict）・
  `actionable_advice()`（★上記を総合したルールベースの日本語「次にやるべきこと」助言。インサイトがある場合は
  保存率を上げる施策・リールでフォロワー外リーチを稼ぐ・プロフィール販売導線の整備を最優先で提示。
  視覚特徴がある場合は「どんな見た目の作品が刺さるか」も助言）・
  `build_summary()`（一括）。
- `suggest.py` — 統計サマリ＋高エンゲージ投稿例＋トレンドをプロンプト化し、`claude-opus-4-8` に
  構造化出力（`messages.parse()` + Pydantic）でリクエスト。投稿案3〜5件（テーマ・キャプション案・
  タグ・タイプ・推奨時間・根拠・予測エンゲージメント）を生成。結果は `result/suggestions/{today}.json`
  にキャッシュ（同日は再課金しない）。`generate_suggestions(force=True)` で再生成。

## ダッシュボード

```bash
# ダッシュボード起動（同じWiFi内のスマホからもアクセス可能）
./run_dashboard.sh
```

起動後、ターミナルに表示されるIPアドレス（例: `http://192.168.x.x:8501`）をスマホブラウザで開く。

### ダッシュボードの構成（`src/dashboard.py`）

サイドバー・フィルターなし。ページ上部の **4タブ** で構成。全データは全期間・全タイプ対象（フィルターなし）。

**デザイン（和紙×藍・モバイルファースト）** — タイトルは「アトリエ分析」。配色・CSSは `dashboard.py` 冒頭の
デザイントークン（`C_PAGE`/`C_BLUE` 等）と `.streamlit/config.toml` のテーマで管理。plotly は共通テンプレート
`pio.templates["atelier"]`（`px.defaults.template`）で全チャートの背景透過・グリッド・colorway（藍/橙/菫）を統一し、
各チャート側では高さ・凡例など図固有の設定だけを上書きする。見出しは明朝（CSS `--serif`）。
CSSは `data-testid` セレクタ依存のため、Streamlitバージョンアップで崩れたら冒頭のCSSブロックだけ直す。
スマホ幅（640px以下）ではStreamlitがカラムを縦積みにするが、KPIタイル・投稿カード（画像＋本文）は
`:has()` セレクタで横並びを維持している。デザインの原型モックは Artifact
（https://claude.ai/code/artifact/ab9bce7b-00d2-4ee8-9569-d236b900bc59）。

#### 🏠 ホームタブ（普段はここだけ）

- **ヒーローカード（北極星）** — 🔖保存率を大数字＋前30日比デルタピルで最上部に単独表示。右（スマホでは下）に
  月別平均保存数のスパークライン（`_monthly_saved_spark`・直近12ヶ月）。**直近30日の投稿のみから算出・タブ切替に非連動**。
  インサイト未取得時は「—」＋収集コマンド案内。
- **重視KPIタイル（3枚）** — 👀平均リーチ・🏠プロフィール訪問（平均）・📈フォロワー純増。各カードに前30日比デルタ付き。
- **補助KPI（「くわしい指標」expanderに格納）** — 🏠ホーム率（投稿時）・🆕フォロワー外リーチ比率・💬エンゲージ率・
  🔁平均シェア数・🔗アカウント全体（プロフィールアクセス/リンククリック）を行形式（`_mrow`）で表示。
  「フォロワー浸透（土台）→ 新規拡散（成長）」の順で**ホーム率とフォロワー外リーチ比率を隣接**させている。
- **フォロワー推移ミニカード** — 現在値＋全期間純増とスパークライン（`_followers_spark`）。詳細はトレンドタブ。
- **ホーム率（投稿時）** — `_account_home_rate_peak()`。`reach_follower ÷ その日のフォロワー数`の直近30日**最大値**
  （＝最もフォロワーに届いた投稿日の値）。**メディア単位のフォロワー別リーチはv22で取れない**ため、アカウント日次
  （`df_account_insights` の `reach_follower`）から算出する。日次は投稿日にスパイクし投稿のない日は残り火（数人）に
  なるため平均ではなくピークを採用。アカウントインサイトの履歴が浅い間（cron開始前）は前30日が無く、デルタは「—」。
- **集計方式** — 比率KPI（保存率・フォロワー外リーチ比率・エンゲージ率）は**リーチ加重 `sum(分子)/sum(リーチ)`**。
  件数KPI（リーチ・プロフィール訪問・シェア）は投稿あたり平均。ヘルパー: `_window_rate`・`_window_mean`・
  `_window_engagement_rate`・`_account_nf_rate`・`_account_home_rate_peak`・`_fmt_delta`。ホームKPIの保存率はリーチ加重のため低リーチ偏りは無い。
- **投稿パフォーマンス一覧** — **縦カードリスト**（左サムネイル・右に順位/日付/タイプ/キャプション1行/指標行）。
  **調整保存率/保存数/リーチ/シェア/いいね/コメント/総エンゲージ率**でソート可
  （HAS_INSIGHTS時の既定は**🔖調整保存率 `saved_rate_adj`**＝低リーチ補正済みで「中身の質」を公平に比較）。📊＝総エンゲージ率（保存・シェア込）。
  ※生の `saved_rate` ソートとリーチ下位足切り（旧 `REACH_PERCENTILE_FOR_RATE`）は廃止し、ベイズ調整に置き換え済み。
  **対象期間セレクタ**（直近3/6/12/24ヶ月・全期間。既定=直近12ヶ月。`PERIOD_OPTIONS`／`_period_window`）で絞り、選んだ期間で `add_saved_rate_adj` を再計算する（保存率の地合いは年々大きく低下しており、全期間だと昔の投稿が上位を独占して「今効く型」が見えないため）。

#### 📈 トレンドタブ（継続・成長の見える化）

全期間・全件が対象（フィルター非連動）。
- **フォロワー数推移** — 全期間折れ線
- **累積投稿数の推移** — 右肩上がりで積み上げを実感
- **月次の平均リーチ・平均保存数**（インサイト取得時のみ）— 立ち上げ期の伸びを月次で確認
- **アカウント日次インサイトの推移**（`df_account_insights` がある時のみ）— プロフィールアクセス・リーチ・リンククリック

#### 📊 詳しい分析タブ（保存/リーチ軸・写真の傾向）

インサイト取得済み投稿のみ対象。いいね基準をやめ販売ファネル軸で集計。未取得時はいいね基準にフォールバック。
内部5サブタブ:
- **📌 タイプ別の効き目** — `media_type` 別に**平均リーチ・平均保存数・平均プロフィール訪問**を棒グラフ＋表
- **🗓️ 投稿タイミング** — 曜日×時間帯ヒートマップ（インサイト時は**平均保存数**基準・未取得時はいいね数）
- **📈 リーチ・発見の推移** — リーチ推移（タイプ色分け）＋フォロワー外リーチ比率の推移（`non_follower_reach_rate` がある時）
- **🔖 ハッシュタグ** — タグ別の**平均保存数 TOP20**（インサイト時）＋使用頻度 TOP20
- **🎨 写真の傾向** — `visual_engagement_analysis` を可視化。各視覚特徴の5分位（最低/低/中/高/最高）帯別の
  平均（調整保存率優先）＋主要色別の平均を棒グラフ表示。**対象期間セレクタ**（既定=直近12ヶ月）で絞り、
  その期間の df に `add_saved_rate_adj` を再計算してから `visual_engagement_analysis` を都度実行（地合い差の混入を防ぐ）。視覚特徴未取得時は `collect_visual.py` 実行を案内

#### 💡 投稿アイデアタブ

全期間データから算出（`build_summary`）。
- **📋 次にやるべきこと** — `actionable_advice()` の先頭3件を常時表示、残りは「もっと見る」expander
- **📌 伸びる条件**（expander）— 最適タイミング・伸びるタイプ・効くタグ・業界トレンド
- **📐 伸びる投稿の型**（expander）— キャプション長・タグ数・投稿ペースとグラフ
- **⚠️ 避けたい条件**（expander）— 反応が低かったパターン
- **🤖 AIで投稿案を作る**（最下部 expander・デフォルト折りたたみ）— ボタン課金・同日キャッシュで連打防止

### データローダー（`src/data_loader.py`）

- `load_profile_data()` — 全プロフィールCSVをまとめてフォロワー推移データに変換
- `load_media_data()` — 最新メディアCSVを読み込み（UTC→JSTに変換済み）
- `merge_follower_at_post_date()` — 各投稿日のフォロワー数を紐付けてエンゲージメント率を計算
- `load_insights_data()` — `result/insights/` の**全**メディア別インサイトCSVを統合し、`id` ごとに最新の非欠損値を採用（日次で直近N件のみ収集しても、過去 `--all` で取得した全履歴のカバレッジが失われない。`groupby.last()` を利用）
- `load_account_insights_data()` — `result/insights/` の全アカウント別インサイトCSVを日次推移として結合
- `load_visual_data()` — `result/visual/` の**全**視覚特徴CSVを統合し、`id` ごとに最新の非欠損特徴を採用（`load_insights_data` と同じ `groupby.last()` 方針）
- `merge_visual()` — メディアデータに `id` で視覚特徴列（brightness等の数値9種＋`dominant_color`）を結合。未取得は欠損のまま
- `add_saved_rate_adj()` — **渡された df の範囲で** m（リーチ加重保存率）・C（reach平均）を計算し `saved_rate_adj` を（再）算出。期間で絞った部分集合に対して呼ぶと**その期間の地合いで再正規化**される（保存率の地合いは年々約60倍下がっており、全期間で比べると昔の投稿が上位を独占して「今効く型」が見えなくなるため、ダッシュボードは直近Nヶ月に絞って本関数を呼び直す）
- `merge_insights()` — メディアデータに `id` でインサイト列を結合。保存率 `saved_rate`・**ベイズ調整保存率 `saved_rate_adj`**（低リーチ補正。`(saved + m*C)/(reach + C)`。m=全体のリーチ加重保存率、C=reach平均。reach分布が古い極小投稿で右に歪むため中央値ではなく平均を採用。リーチが小さい投稿の保存率を全体平均へ引き寄せ、まぐれの高保存率を抑える）・リーチベースのエンゲージ率 `reach_engagement_rate`・フォロワー外リーチ比率 `non_follower_reach_rate`（`reach_non_follower`／`reach`）・総エンゲージ率 `total_engagement_rate`（`total_interactions`＝いいね＋コメント＋保存＋シェア ÷ 投稿時点フォロワー。`total_interactions` が無い投稿は基本ERにフォールバック）を算出
- `load_competitor_data()` — `result/competitors/` の各競合の最新メディアCSVを結合（`competitor`列付き）
- `load_hashtag_data()` — `result/hashtags/` の各タグの最新CSVを結合（`search_hashtag`列付き）

## 注意事項

- API制限（error code 4）に引っかかった場合は1時間後に再実行する
- ハッシュタグ収集は「7日間で30ユニークタグまで」。`TREND_HASHTAGS` は絞り、頻度を抑える
- ハッシュタグの top_media では投稿者のフォロワー数・ユーザー名は取得できない（いいね/コメント/キャプション/タイプは取得可）
- `result/` と `.env` は `.gitignore` で除外済み
- ダッシュボードのサムネイルはInstagramのCDN URLのため、古い投稿は表示されない場合がある（有効期限あり）
- エンゲージメント率 = (いいね数 + コメント数) / 投稿日時点のフォロワー数 × 100（基本ER。`engagement_rate`。散布図やbest_slots等の全期間比較に使用）。
  なお**投稿パフォーマンス一覧の📊は保存・シェアを含む総エンゲージ率 `total_engagement_rate`**（Meta の `total_interactions` 基準）を表示・並べ替え対象にする。販売/受注目的では保存が北極星のため、一覧は保存・シェア込みで評価する
- AI投稿案は `claude-opus-4-8` を使用。生成1回ごとに少額課金が発生（同日キャッシュで再課金回避）
- インサイトとメディアCSVは `id` で結合する。`id` 列はある時点から追加されたため、それ以前のメディアCSVには `id` が無くインサイトを結合できない（`collect.py` を再実行すれば最新CSVに `id` が付与される）
- `profile_visits`（投稿経由のプロフィール訪問）と `profile_views`（アカウント全体のプロフィールアクセス）は別物
- アカウントインサイトは `period=day`（当日分のみ）。推移を見るには日次cron（`run.sh`）で毎日蓄積する
- インサイトAPIにもレート制限（毎時200リクエスト）あり。`collect_insights.py` はデフォルトで直近200件のみ取得する
- APIバージョンは v22.0。欲しいインサイト指標は v22 ですべて取得可能（バージョンアップは任意）。`impressions` と非Reelsの `video_views` は2025年に廃止済み（それぞれ `reach`・`views` で代替）
- 視覚特徴（`collect_visual.py`）は**ローカル軽量分析**のみで、モチーフ（何が描かれているか）は判定できない（色み・明るさ・余白・描き込み量などの物理量）。意味的な分析が必要になったら Claude Vision（少額課金）への拡張を検討する
- 視覚特徴は **CDN URL から取得できる投稿のみ**（期限切れの古い投稿は欠損）。`collect_visual.py` を定期実行して取れるうちに蓄積する。画像ファイルは保存せず数値特徴だけを `result/visual/` にキャッシュする方針
- `visual_engagement_analysis` の結果は相関であって因果ではない。帯ごとの件数が少ない初期は方向性の参考として扱う
