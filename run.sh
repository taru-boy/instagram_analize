#!/bin/bash
BASE_DIR=/home/taru-boy/Desktop/insta-open-main
LOG_DIR=$BASE_DIR/logs
mkdir -p $LOG_DIR

# 妻アカウントの収集（毎回）
$BASE_DIR/.venv/bin/python $BASE_DIR/src/collect.py >> $LOG_DIR/collect.log 2>&1

# 競合アカウントの収集（毎回でも可。Business Discovery のレート制限に注意）
$BASE_DIR/.venv/bin/python $BASE_DIR/src/collect_competitors.py >> $LOG_DIR/competitors.log 2>&1

# ハッシュタグ人気投稿の収集
#   ※ IG Hashtag Search は「7日間で30ユニークタグまで」制限があるため、
#     このスクリプトは週1〜2回程度の頻度で実行すること（毎日は避ける）。
$BASE_DIR/.venv/bin/python $BASE_DIR/src/collect_hashtags.py >> $LOG_DIR/hashtags.log 2>&1
