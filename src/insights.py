# 統計ベースの「伸びる条件」抽出ロジック
# 妻の過去データ・競合・ハッシュタグ人気投稿から、ルールで傾向を集計する純関数群。
# dashboard.py / suggest.py の両方から再利用する。
import pandas as pd

MEDIA_TYPE_JA = {"IMAGE": "画像", "CAROUSEL_ALBUM": "スライド", "VIDEO": "動画"}


def _engagement_col(df: pd.DataFrame) -> str:
    """エンゲージメント率があればそれを、なければ like_count を指標に使う。"""
    if "engagement_rate" in df.columns and df["engagement_rate"].notna().any():
        return "engagement_rate"
    return "like_count"


def best_posting_slots(df_media: pd.DataFrame, top_n: int = 3, min_count: int = 2) -> list:
    """
    平均エンゲージメントが高い「曜日 × 時間帯」の組み合わせ上位を返す。

    Returns
    -------
    list[dict]
        [{day_name, hour, avg, count}] のリスト（avgの降順）
    """
    if df_media.empty or "day_name" not in df_media.columns:
        return []
    col = _engagement_col(df_media)
    grp = (
        df_media.groupby(["day_name", "hour"])
        .agg(avg=(col, "mean"), count=(col, "count"))
        .reset_index()
    )
    grp = grp[grp["count"] >= min_count]
    if grp.empty:
        # データが少ない場合は件数フィルタを外す
        grp = (
            df_media.groupby(["day_name", "hour"])
            .agg(avg=(col, "mean"), count=(col, "count"))
            .reset_index()
        )
    grp = grp.sort_values("avg", ascending=False).head(top_n)
    return grp.round(2).to_dict("records")


def best_media_type(df_media: pd.DataFrame) -> list:
    """
    メディアタイプ別の平均いいね・コメント・件数を、平均いいねの降順で返す。

    Returns
    -------
    list[dict]
        [{media_type, type_ja, avg_like, avg_comment, count}]
    """
    if df_media.empty or "media_type" not in df_media.columns:
        return []
    grp = (
        df_media.groupby("media_type")
        .agg(
            avg_like=("like_count", "mean"),
            avg_comment=("comments_count", "mean"),
            count=("like_count", "count"),
        )
        .reset_index()
    )
    grp["type_ja"] = grp["media_type"].map(MEDIA_TYPE_JA).fillna(grp["media_type"])
    grp = grp.sort_values("avg_like", ascending=False)
    return grp.round(1).to_dict("records")


def _explode_hashtags(df: pd.DataFrame) -> pd.DataFrame:
    """hashtag 列（改行区切り）を1タグ1行に展開し、like_countを付与する。"""
    rows = []
    for _, row in df.iterrows():
        raw = row.get("hashtag")
        if pd.isna(raw) or str(raw).strip() == "":
            continue
        for tag in str(raw).split("\n"):
            tag = tag.strip()
            if tag:
                rows.append({"hashtag": tag, "like_count": row.get("like_count", 0)})
    return pd.DataFrame(rows)


def top_hashtags_by_engagement(df_media: pd.DataFrame, top_n: int = 10) -> list:
    """
    妻の投稿で、平均いいね数が高いハッシュタグ上位を返す（使用2回以上）。

    Returns
    -------
    list[dict]
        [{hashtag, avg_like, count}]
    """
    if df_media.empty:
        return []
    tags = _explode_hashtags(df_media)
    if tags.empty:
        return []
    grp = (
        tags.groupby("hashtag")
        .agg(avg_like=("like_count", "mean"), count=("like_count", "count"))
        .reset_index()
    )
    grp = grp[grp["count"] >= 2]
    if grp.empty:
        grp = (
            tags.groupby("hashtag")
            .agg(avg_like=("like_count", "mean"), count=("like_count", "count"))
            .reset_index()
        )
    grp = grp.sort_values("avg_like", ascending=False).head(top_n)
    return grp.round(1).to_dict("records")


def trending_topics(
    df_competitors: pd.DataFrame, df_hashtags: pd.DataFrame, top_n: int = 15
) -> list:
    """
    競合・ハッシュタグ人気投稿で「よく使われている／よく伸びているタグ」を集計。
    出現頻度と平均いいね数の両方を見られるようにして返す。

    Returns
    -------
    list[dict]
        [{hashtag, count, avg_like}]（出現頻度の降順）
    """
    frames = []
    for df in (df_competitors, df_hashtags):
        if df is not None and not df.empty:
            frames.append(_explode_hashtags(df))
    if not frames:
        return []
    tags = pd.concat(frames, ignore_index=True)
    if tags.empty:
        return []
    grp = (
        tags.groupby("hashtag")
        .agg(count=("like_count", "count"), avg_like=("like_count", "mean"))
        .reset_index()
    )
    grp = grp.sort_values(["count", "avg_like"], ascending=False).head(top_n)
    return grp.round(1).to_dict("records")


def _caption_len(value) -> int:
    """キャプションの文字数（NaN/空は0）。"""
    if pd.isna(value):
        return 0
    return len(str(value).strip())


def _hashtag_count(value) -> int:
    """1投稿あたりのハッシュタグ数（改行区切り）。"""
    if pd.isna(value) or str(value).strip() == "":
        return 0
    return len([t for t in str(value).split("\n") if t.strip()])


def _bin_engagement(df: pd.DataFrame, value_series: pd.Series, bins: list, labels: list) -> list:
    """
    値の区間ごとに平均エンゲージと件数を集計し、平均の降順で返す共通処理。
    """
    col = _engagement_col(df)
    work = pd.DataFrame({"_v": value_series.values, "_eng": df[col].values})
    work["_band"] = pd.cut(work["_v"], bins=bins, labels=labels, right=True)
    grp = (
        work.dropna(subset=["_band"])
        .groupby("_band", observed=True)
        .agg(avg=("_eng", "mean"), count=("_eng", "count"))
        .reset_index()
        .rename(columns={"_band": "band"})
    )
    grp["band"] = grp["band"].astype(str)
    grp = grp.sort_values("avg", ascending=False)
    return grp.round(2).to_dict("records")


def _band_of(value: float, bins: list, labels: list):
    """単一の値がどの区間に入るかのラベルを返す。"""
    res = pd.cut([value], bins=bins, labels=labels, right=True)
    return None if pd.isna(res[0]) else str(res[0])


def caption_length_analysis(df_media: pd.DataFrame) -> dict:
    """
    キャプション文字数の区間別エンゲージを集計し、最適レンジ・現在の平均・現在の区間を返す。
    """
    if df_media.empty or "caption" not in df_media.columns:
        return {}
    lengths = df_media["caption"].map(_caption_len)
    bins = [-1, 50, 100, 200, 400, 100000]
    labels = ["〜50字", "51〜100字", "101〜200字", "201〜400字", "401字〜"]
    ranking = _bin_engagement(df_media, lengths, bins, labels)
    if not ranking:
        return {}
    current_avg = round(float(lengths.mean()), 1)
    return {
        "ranking": ranking,
        "best_band": ranking[0]["band"],
        "current_avg": current_avg,
        "current_band": _band_of(current_avg, bins, labels),
    }


def hashtag_count_analysis(df_media: pd.DataFrame) -> dict:
    """
    1投稿あたりのハッシュタグ数の区間別エンゲージを集計し、最適レンジ・現在の平均・現在の区間を返す。
    best_band は最良区間だが、推奨用途では「0個」を除いた best_actionable_band を使う
    （タグ0個の推奨は通常適切でないため）。
    """
    if df_media.empty or "hashtag" not in df_media.columns:
        return {}
    counts = df_media["hashtag"].map(_hashtag_count)
    bins = [-1, 0, 5, 10, 15, 1000]
    labels = ["0個", "1〜5個", "6〜10個", "11〜15個", "16個〜"]
    ranking = _bin_engagement(df_media, counts, bins, labels)
    if not ranking:
        return {}
    nonzero = [r for r in ranking if r["band"] != "0個"]
    current_avg = round(float(counts.mean()), 1)
    return {
        "ranking": ranking,
        "best_band": ranking[0]["band"],
        "best_actionable_band": nonzero[0]["band"] if nonzero else ranking[0]["band"],
        "current_avg": current_avg,
        "current_band": _band_of(current_avg, bins, labels),
    }


def posting_cadence(df_media: pd.DataFrame, recent_days: int = 90) -> dict:
    """
    投稿ペースを集計する。直近 recent_days の週あたり投稿数、平均投稿間隔、
    過去（それ以前）との比較を返す。
    """
    if df_media.empty or "timestamp_jst" not in df_media.columns:
        return {}
    ts = pd.to_datetime(df_media["timestamp_jst"]).dropna().sort_values()
    if len(ts) < 2:
        return {}
    latest = ts.max()
    cutoff = latest - pd.Timedelta(days=recent_days)
    recent = ts[ts >= cutoff]
    older = ts[ts < cutoff]

    recent_per_week = round(len(recent) / (recent_days / 7), 2)
    # 平均投稿間隔（日）
    intervals = ts.diff().dropna().dt.total_seconds() / 86400
    avg_interval = round(float(intervals.mean()), 1) if not intervals.empty else None

    # 過去のペース（cutoff以前のデータがある場合のみ）
    older_per_week = None
    if len(older) >= 2:
        span_days = max((older.max() - older.min()).days, 1)
        older_per_week = round(len(older) / (span_days / 7), 2)

    trend = "横ばい"
    if older_per_week is not None:
        if recent_per_week < older_per_week * 0.7:
            trend = "ペースダウン"
        elif recent_per_week > older_per_week * 1.3:
            trend = "ペースアップ"

    return {
        "recent_per_week": recent_per_week,
        "older_per_week": older_per_week,
        "avg_interval_days": avg_interval,
        "trend": trend,
        "recent_days": recent_days,
    }


def low_performers(df_media: pd.DataFrame, bottom_n: int = 3, min_count: int = 2) -> dict:
    """
    反応が低い「避けたい条件」を抽出する。
    平均エンゲージ下位の曜日×時間帯と、最も伸びないメディアタイプを返す。
    """
    if df_media.empty or "day_name" not in df_media.columns:
        return {}
    col = _engagement_col(df_media)

    grp = (
        df_media.groupby(["day_name", "hour"])
        .agg(avg=(col, "mean"), count=(col, "count"))
        .reset_index()
    )
    grp = grp[grp["count"] >= min_count]
    worst_slots = (
        grp.sort_values("avg").head(bottom_n).round(2).to_dict("records")
        if not grp.empty
        else []
    )

    types = best_media_type(df_media)  # 平均いいね降順
    worst_type = types[-1] if len(types) >= 2 else None

    return {"worst_slots": worst_slots, "worst_type": worst_type}


def competitor_gap(
    df_media: pd.DataFrame, df_competitors: pd.DataFrame, top_n: int = 10
) -> dict:
    """
    競合がよく使うのに妻が未使用/低頻度のハッシュタグ候補と、
    競合 vs 妻の平均いいね比較を返す。競合データが無ければ空。
    """
    if df_competitors is None or df_competitors.empty:
        return {}

    my_tags = set()
    if not df_media.empty:
        my_tags = set(_explode_hashtags(df_media)["hashtag"].tolist())

    comp_tags = _explode_hashtags(df_competitors)
    if comp_tags.empty:
        gap_tags = []
    else:
        freq = comp_tags["hashtag"].value_counts().reset_index()
        freq.columns = ["hashtag", "count"]
        freq = freq[~freq["hashtag"].isin(my_tags)]
        gap_tags = freq.head(top_n).to_dict("records")

    my_avg = (
        round(float(df_media["like_count"].mean()), 1)
        if not df_media.empty
        else None
    )
    comp_avg = round(float(df_competitors["like_count"].mean()), 1)

    return {
        "unused_popular_tags": gap_tags,
        "my_avg_like": my_avg,
        "competitor_avg_like": comp_avg,
        "competitor_count": int(df_competitors.get("competitor", pd.Series(dtype=str)).nunique()),
    }


def actionable_advice(
    df_media: pd.DataFrame,
    df_competitors: pd.DataFrame = None,
    df_hashtags: pd.DataFrame = None,
) -> list:
    """
    ★各種統計を総合し、ルールベースで日本語の箇条書きアドバイスを生成する（AI不使用）。
    各助言は数値根拠付き。返り値は文字列のリスト。
    """
    if df_competitors is None:
        df_competitors = pd.DataFrame()
    if df_hashtags is None:
        df_hashtags = pd.DataFrame()
    if df_media.empty:
        return ["データがまだ少ないため、まずは投稿を続けてデータを貯めましょう。"]

    advice = []

    # 1. 伸びるタイプを増やす提案
    types = best_media_type(df_media)
    if len(types) >= 2:
        best, worst = types[0], types[-1]
        total = sum(t["count"] for t in types)
        best_share = best["count"] / total if total else 0
        if best["avg_like"] >= worst["avg_like"] * 1.2 and best_share < 0.5:
            advice.append(
                f"「{best['type_ja']}」の平均いいねが{best['avg_like']}と高めですが投稿割合は"
                f"{best_share*100:.0f}%。{best['type_ja']}を増やすと伸びやすいです。"
            )

    # 2. 最適な投稿タイミング
    slots = best_posting_slots(df_media)
    if slots:
        s = slots[0]
        advice.append(
            f"{s['day_name']}曜 {s['hour']}時台が好反応です。次の投稿はこの時間帯を狙いましょう。"
        )

    # 3. ハッシュタグ数の最適化（0個推奨は避け、既に最適帯なら助言しない）
    hc = hashtag_count_analysis(df_media)
    if hc:
        target = hc.get("best_actionable_band")
        if target and hc.get("current_band") != target:
            advice.append(
                f"ハッシュタグは「{target}」が最も伸びています（今の平均は{hc['current_avg']:.0f}個）。"
            )

    # 4. キャプション長の最適化（既に最適帯なら助言しない）
    cl = caption_length_analysis(df_media)
    if cl and cl.get("best_band") and cl.get("current_band") != cl["best_band"]:
        advice.append(
            f"キャプションは「{cl['best_band']}」の投稿が好反応です"
            f"（今の平均は{cl['current_avg']:.0f}字）。"
        )

    # 5. 投稿ペース
    cad = posting_cadence(df_media)
    if cad:
        if cad["trend"] == "ペースダウン":
            advice.append(
                f"最近の投稿ペースが落ちています（直近は週{cad['recent_per_week']}件）。"
                "ペースを戻すと露出が安定します。"
            )
        elif cad["trend"] == "ペースアップ":
            advice.append(
                f"投稿ペースが上がっています（直近は週{cad['recent_per_week']}件）。良い調子です。"
            )

    # 6. 効くタグの継続
    top_tags = top_hashtags_by_engagement(df_media, top_n=3)
    if top_tags:
        names = "　".join(f"#{t['hashtag']}" for t in top_tags)
        advice.append(f"反応が良いタグは継続を: {names}")

    # 7. 競合から学ぶ
    gap = competitor_gap(df_media, df_competitors)
    if gap and gap.get("unused_popular_tags"):
        top_gap = gap["unused_popular_tags"][0]
        advice.append(
            f"競合がよく使う #{top_gap['hashtag']} を未使用です。試す価値があります。"
        )

    return advice


def build_summary(
    df_media: pd.DataFrame,
    df_competitors: pd.DataFrame = None,
    df_hashtags: pd.DataFrame = None,
) -> dict:
    """
    上記の統計をまとめて1つの辞書にする。dashboard表示・AIプロンプト両用。
    """
    if df_competitors is None:
        df_competitors = pd.DataFrame()
    if df_hashtags is None:
        df_hashtags = pd.DataFrame()
    return {
        "best_slots": best_posting_slots(df_media),
        "best_types": best_media_type(df_media),
        "top_hashtags": top_hashtags_by_engagement(df_media),
        "trending_topics": trending_topics(df_competitors, df_hashtags),
        "caption_length": caption_length_analysis(df_media),
        "hashtag_count": hashtag_count_analysis(df_media),
        "cadence": posting_cadence(df_media),
        "low_performers": low_performers(df_media),
        "competitor_gap": competitor_gap(df_media, df_competitors),
        "advice": actionable_advice(df_media, df_competitors, df_hashtags),
        "total_posts": int(len(df_media)),
    }
