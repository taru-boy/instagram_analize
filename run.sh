#!/bin/bash
BASE_DIR=/home/taru-boy/Desktop/insta-open-main
LOG_DIR=$BASE_DIR/logs
mkdir -p $LOG_DIR

# 失敗の通知先（journaling リポジトリの LINE 送信スクリプトを共有）。
# 0時に走るので LINE_DEFER=1 でキューに積み、朝 06:30 の line_flush.sh でまとめて届く。
SEND_LINE=/home/taru-boy/Desktop/journaling/scripts/send_line.sh
FAILED=()

# 1ステップ実行し、終了コードが0以外なら FAILED に記録する
#   $1: 表示名  $2: ログファイル名  以降: 実行するコマンド
step() {
  local name=$1 log=$LOG_DIR/$2
  shift 2
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$log"
  if ! "$@" >> "$log" 2>&1; then
    FAILED+=("$name（logs/$(basename "$log")）")
  fi
}

# 妻アカウントの収集（毎回）
step "投稿収集" collect.log $BASE_DIR/.venv/bin/python $BASE_DIR/src/collect.py

# インサイト収集（リーチ・保存・シェア・プロフィールアクセスなど）
#   ※ アカウント日次インサイト(period=day)を毎日蓄積すると推移が見られる。
#     メディア別は直近200件のみ取得（レート制限対策。全件は --all）。
step "インサイト収集" insights.log $BASE_DIR/.venv/bin/python $BASE_DIR/src/collect_insights.py

# 投稿画像の視覚特徴収集（色・明るさ・余白など。API課金なし）
#   ※ collect.py の後に実行。直近200件のうち未処理のみ取得（増分）。
#     CDN URL は期限切れで消えるため、取れるうちに蓄積しておく。
step "視覚特徴収集" visual.log $BASE_DIR/.venv/bin/python $BASE_DIR/src/collect_visual.py

# 失敗があれば LINE で知らせる（トークン失効・API制限などで黙って止まるのを防ぐ）
if [ ${#FAILED[@]} -gt 0 ]; then
  {
    echo "⚠️ Instagram収集が失敗しました（$(date '+%m/%d')）"
    for f in "${FAILED[@]}"; do echo "・$f"; done
    echo ""
    echo "直近のエラー:"
    grep -hE "エラー|error|Error|失敗|中断" "$LOG_DIR"/collect.log "$LOG_DIR"/insights.log 2>/dev/null | tail -n 3 | cut -c1-200
    echo ""
    echo "code 190 ならトークン失効、code 4 なら API 制限（1時間後に再実行）。"
  } | LINE_DEFER=${LINE_DEFER-1} "$SEND_LINE" || echo "LINE 通知に失敗しました" >> "$LOG_DIR/collect.log"
  exit 1
fi
