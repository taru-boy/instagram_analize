# Claude AI による投稿案の生成（構造化出力）
# 統計サマリ（insights）＋妻の高エンゲージ投稿例＋競合/ハッシュタグのトレンドを
# プロンプトに詰めて claude-opus-4-8 に渡し、投稿案リストを得る。
import json
import os
from datetime import datetime as dt
from typing import List, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from data_loader import (load_competitor_data, load_hashtag_data,
                         load_media_data, load_profile_data,
                         merge_follower_at_post_date)
from insights import MEDIA_TYPE_JA, build_summary

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULT_DIR = os.path.join(_BASE, "result")
SUGGEST_DIR = os.path.join(RESULT_DIR, "suggestions")

MODEL = "claude-opus-4-8"


class MissingAPIKeyError(RuntimeError):
    """ANTHROPIC_API_KEY が未設定のときに送出する。"""


class PostSuggestion(BaseModel):
    theme: str = Field(description="投稿のテーマ・題材（画家の作品/制作過程など）")
    caption_draft: str = Field(description="そのまま使えるキャプション案（日本語）")
    hashtags: List[str] = Field(description="推奨ハッシュタグ（#なしの語のリスト）")
    media_type: Literal["画像", "スライド", "動画"] = Field(description="推奨メディアタイプ")
    best_time: str = Field(description="推奨する投稿の曜日・時間帯")
    rationale: str = Field(description="なぜ伸びそうかの根拠（データに基づく）")
    predicted_level: Literal["高", "中", "低"] = Field(description="予測エンゲージメント")


class SuggestionList(BaseModel):
    suggestions: List[PostSuggestion]


def _sample_top_posts(df_media: pd.DataFrame, n: int = 8) -> str:
    """妻の高エンゲージ投稿をプロンプト用に要約テキスト化する。"""
    if df_media.empty:
        return "（過去投稿データがありません）"
    sort_col = (
        "engagement_rate"
        if "engagement_rate" in df_media.columns
        and df_media["engagement_rate"].notna().any()
        else "like_count"
    )
    top = df_media.sort_values(sort_col, ascending=False).head(n)
    lines = []
    for _, r in top.iterrows():
        type_ja = MEDIA_TYPE_JA.get(r.get("media_type"), r.get("media_type"))
        cap = str(r.get("caption", "") or "").replace("\n", " ")[:80]
        tags = str(r.get("hashtag", "") or "").replace("\n", " ")
        eng = ""
        if "engagement_rate" in df_media.columns and pd.notna(r.get("engagement_rate")):
            eng = f", ER {r['engagement_rate']}%"
        lines.append(
            f"- [{type_ja}] いいね{int(r['like_count'])} "
            f"コメント{int(r['comments_count'])}{eng} / タグ: {tags} / 例: {cap}"
        )
    return "\n".join(lines)


def _build_prompt(df_media, summary) -> str:
    """統計サマリと投稿例から、Claudeへのユーザープロンプトを組み立てる。"""
    parts = [
        "以下は妻（画家）のInstagramの分析データです。これを踏まえて、",
        "次に投稿すべき具体的な投稿案を3〜5件提案してください。\n",
        f"## 総投稿数\n{summary['total_posts']} 件\n",
        "## 伸びている投稿タイプ（平均いいね順）",
    ]
    for t in summary["best_types"]:
        parts.append(
            f"- {t['type_ja']}: 平均いいね{t['avg_like']} / "
            f"平均コメント{t['avg_comment']} / {t['count']}件"
        )
    parts.append("\n## 反応が良い曜日・時間帯")
    for s in summary["best_slots"]:
        parts.append(f"- {s['day_name']}曜 {s['hour']}時台（{s['count']}件平均）")
    parts.append("\n## エンゲージメントが高いハッシュタグ（妻の過去投稿）")
    for h in summary["top_hashtags"]:
        parts.append(f"- #{h['hashtag']}（平均いいね{h['avg_like']}）")
    parts.append("\n## 業界トレンド（競合・人気タグ投稿で多用/高反応のタグ）")
    for tt in summary["trending_topics"]:
        parts.append(f"- #{tt['hashtag']}（出現{tt['count']}回 / 平均いいね{tt['avg_like']}）")
    parts.append("\n## 妻の高エンゲージ投稿の例")
    parts.append(_sample_top_posts(df_media))
    parts.append(
        "\n各提案には、テーマ・キャプション案・推奨ハッシュタグ・推奨メディアタイプ・"
        "推奨投稿時間帯・伸びそうな根拠・予測エンゲージメント(高/中/低)を含めてください。"
    )
    return "\n".join(parts)


SYSTEM_PROMPT = (
    "あなたはInstagramの成長を支援するSNSマーケティングの専門家です。"
    "対象は日本語で発信する画家（アーティスト）のアカウントです。"
    "作品そのもの・制作過程・アトリエの様子・画材・展示情報など、画家ならではの題材を活かし、"
    "データの傾向（伸びるタイプ・時間帯・タグ）に根拠を置いた、実行可能で具体的な投稿案を出してください。"
    "キャプション案はそのまま使える自然な日本語で書いてください。"
)


def _load_all():
    """ダッシュボードと同じ手順でデータを読み込み、エンゲージメント率を付与する。"""
    df_profile = load_profile_data(RESULT_DIR)
    df_media = load_media_data(RESULT_DIR)
    if not df_media.empty and not df_profile.empty:
        df_media = merge_follower_at_post_date(df_media, df_profile)
    df_comp = load_competitor_data(RESULT_DIR)
    df_tags = load_hashtag_data(RESULT_DIR)
    return df_media, df_comp, df_tags


def _cache_path(today: str) -> str:
    return os.path.join(SUGGEST_DIR, f"{today}.json")


def generate_suggestions(force: bool = False) -> dict:
    """
    投稿案を生成して返す。同日のキャッシュがあれば再課金せずそれを返す。

    Parameters
    ----------
    force : bool
        True の場合キャッシュを無視して再生成する。

    Returns
    -------
    dict
        {"suggestions": [...], "generated_at": "..."} 形式。

    Raises
    ------
    MissingAPIKeyError
        ANTHROPIC_API_KEY が未設定のとき。
    """
    load_dotenv(dotenv_path=os.path.join(_BASE, ".env"))
    today = dt.now().strftime("%Y-%m-%d")

    cache = _cache_path(today)
    if not force and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY が設定されていません。.env に追加してください。"
        )

    # import を関数内に置き、anthropic 未インストールでも他機能を壊さない
    import anthropic

    df_media, df_comp, df_tags = _load_all()
    summary = build_summary(df_media, df_comp, df_tags)
    user_prompt = _build_prompt(df_media, summary)

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=SuggestionList,
    )

    parsed: SuggestionList = response.parsed_output
    result = {
        "generated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": MODEL,
        "suggestions": [s.model_dump() for s in parsed.suggestions],
    }

    os.makedirs(SUGGEST_DIR, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    out = generate_suggestions()
    print(json.dumps(out, ensure_ascii=False, indent=2))
