"""
週次アクションレポート（プッシュ型）。

ダッシュボードを開かなくても「先週どうだったか」「今週なにを投稿するか」が届くよう、
直近7日の投稿・アカウント指標と、月間4週サイクルに沿った今週のテーマを
短い文面にまとめて LINE（journaling リポジトリの send_line.sh）で送る。AI 不使用・無料。

使い方:
    python src/weekly_report.py --dry-run   # 文面を標準出力に出すだけ（送らない）
    python src/weekly_report.py             # LINE に送る
"""

import argparse
import os
import subprocess
import sys

import pandas as pd

from data_loader import RESULT_DIR, load_account_insights_data, load_merged_media
from insights import (MEDIA_TYPE_JA, STALL_DAYS, build_summary,
                      posting_cadence, this_week_actions)

SEND_LINE = os.getenv(
    "SEND_LINE", os.path.expanduser("~/Desktop/journaling/scripts/send_line.sh")
)

def _short_caption(text, n: int = 18) -> str:
    first = str(text or "").strip().split("\n")[0].strip()
    return first[:n] + ("…" if len(first) > n else "")


def _fmt_int(v) -> str:
    return "—" if pd.isna(v) else f"{int(v):,}"


def _sum_window(df: pd.DataFrame, col: str, start, end):
    if df.empty or col not in df.columns:
        return None
    w = df[(df["date"] >= start) & (df["date"] < end)]
    return None if w.empty else float(w[col].sum())


def build_report(now: pd.Timestamp | None = None) -> str:
    now = pd.Timestamp.now() if now is None else now
    today = now.normalize()
    week_start = today - pd.Timedelta(days=7)
    prev_start = today - pd.Timedelta(days=14)

    df_profile, df_media = load_merged_media(RESULT_DIR)
    df_ai = load_account_insights_data(RESULT_DIR)
    lines = [f"🖌️ 週次レポート（{week_start:%m/%d}〜{(today - pd.Timedelta(days=1)):%m/%d}）"]

    # --- 先週の投稿 ---
    ts = df_media["timestamp_jst"]
    week = df_media[(ts >= week_start) & (ts < today)].sort_values("timestamp_jst")
    lines.append("")
    lines.append(f"■ 先週の投稿 {len(week)}件（目標 週1〜2件）")
    for _, r in week.iterrows():
        type_ja = MEDIA_TYPE_JA.get(r["media_type"], r["media_type"])
        lines.append(
            f"・{r['timestamp_jst']:%m/%d} {type_ja}「{_short_caption(r.get('caption'))}」"
            f" リーチ{_fmt_int(r.get('reach'))}・保存{_fmt_int(r.get('saved'))}"
        )
    cad = posting_cadence(df_media, now=now)
    # STALL_DAYS 以上は「今週やること」側で最優先の注意として出すので、ここでは軽めに
    if cad and 7 <= cad["days_since_last"] < STALL_DAYS:
        lines.append(f"最後の投稿から{cad['days_since_last']}日空いています")

    # --- アカウント全体（先週 vs 前の週）---
    if not df_ai.empty:
        lines.append("")
        lines.append("■ アカウント全体（前の週比）")
        for col, label in [("profile_views", "プロフィール訪問"), ("website_clicks", "ショップへのリンククリック")]:
            cur = _sum_window(df_ai, col, week_start, today)
            prev = _sum_window(df_ai, col, prev_start, week_start)
            if cur is None:
                continue
            diff = "" if prev is None else f"（{cur - prev:+,.0f}）"
            lines.append(f"・{label} {cur:,.0f}{diff}")
    if not df_profile.empty:
        upto = df_profile[df_profile["date"] <= today]
        past = df_profile[df_profile["date"] <= week_start]
        if not upto.empty and not past.empty:
            now_f = int(upto["followers_count"].iloc[-1])
            gain = now_f - int(past["followers_count"].iloc[-1])
            lines.append(f"・フォロワー {now_f:,}人（{gain:+,}）")

    # --- 今週やること ---
    todo = this_week_actions(df_media, now=now)
    lines.append("")
    lines.append(f"■ 今週のテーマ: {todo['theme']}")
    lines.append(f"→ {todo['hint']}")
    for note in todo["notes"]:
        lines.append(f"→ {note}")

    # 統計ベースの助言から、投稿ペース以外の上位2件を添える
    advice = [
        a for a in build_summary(df_media).get("advice", [])
        if "投稿ペース" not in a and "最後の投稿から" not in a
    ]
    if advice:
        lines.append("")
        lines.append("■ データからのヒント")
        for a in advice[:2]:
            lines.append(f"・{a}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="週次アクションレポートを LINE に送る")
    parser.add_argument("--dry-run", action="store_true", help="送らずに文面を表示する")
    args = parser.parse_args()

    text = build_report()
    if args.dry_run:
        print(text)
        return
    result = subprocess.run([SEND_LINE], input=text, text=True)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
