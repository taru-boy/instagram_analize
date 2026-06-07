#!/bin/bash
BASE_DIR=/home/taru-boy/Desktop/insta-open-main
LOG_DIR=$BASE_DIR/logs
mkdir -p $LOG_DIR
$BASE_DIR/.venv/bin/python $BASE_DIR/src/collect.py >> $LOG_DIR/collect.log 2>&1
