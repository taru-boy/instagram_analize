# 統計ベースの「伸びる条件」抽出ロジック
# 妻の過去データ・競合・ハッシュタグ人気投稿から、ルールで傾向を集計する純関数群。
# dashboard.py / weekly_report.py の両方から再利用する。
import pandas as pd

from data_loader import add_saved_rate_adj

MEDIA_TYPE_JA = {"IMAGE": "画像", "CAROUSEL_ALBUM": "スライド", "VIDEO": "動画"}

# 「今効く型」を見るための既定の分析期間（ダッシュボードの期間セレクタ既定と揃える）
RECENT_MONTHS = 12


def recent_window(df_media: pd.DataFrame, months: int | None = RECENT_MONTHS) -> pd.DataFrame:
    """
    直近 months ヶ月の投稿に絞り、その期間の地合いで saved_rate_adj を再計算して返す。
    months=None なら全期間（再計算もしない）。
    """
    if months is None or df_media.empty or "timestamp_jst" not in df_media.columns:
        return df_media
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
    df = df_media[pd.to_datetime(df_media["timestamp_jst"]) >= cutoff]
    if "saved_rate_adj" in df.columns:
        df = add_saved_rate_adj(df)
    return df.reset_index(drop=True)

# 視覚特徴（collect_visual.py / data_loader.merge_visual が付与）の日本語ラベル。
# 値の大小に意味がある連続特徴のみ（dominant_color はカテゴリなので別扱い）。
VISUAL_NUMERIC_FEATURES = {
    "brightness": "明るさ",
    "saturation": "彩度",
    "contrast": "コントラスト",
    "colorfulness": "色の豊かさ",
    "warm_ratio": "暖色の多さ",
    "whitespace_ratio": "余白の多さ",
    "edge_density": "描き込み量",
    "palette_size": "色数",
    "sharpness": "鮮明さ",
}


def _engagement_col(df: pd.DataFrame) -> str:
    """
    タイミング・キャプション長・タグ数などの比較に使う指標列。
    作品販売の北極星である保存を優先し、_visual_engagement_col と同じ優先順位
    （調整保存率 → 保存率 → 基本ER → いいね数）で選ぶ。
    """
    return _visual_engagement_col(df)[0]


def engagement_label(df: pd.DataFrame) -> str:
    """_engagement_col が選んだ指標の日本語ラベル（グラフの軸名用）。"""
    return _visual_engagement_col(df)[1]


def _visual_engagement_col(df: pd.DataFrame) -> tuple:
    """
    視覚分析で使う指標列とラベルを返す。作品販売の北極星である保存率を優先し、
    低リーチ補正済みのベイズ調整保存率があれば最優先で使う
    （無ければ生の保存率 → 基本ER → いいね数にフォールバック）。
    """
    if "saved_rate_adj" in df.columns and df["saved_rate_adj"].notna().any():
        return "saved_rate_adj", "調整保存率"
    if "saved_rate" in df.columns and df["saved_rate"].notna().any():
        return "saved_rate", "保存率"
    if "engagement_rate" in df.columns and df["engagement_rate"].notna().any():
        return "engagement_rate", "エンゲージ率"
    return "like_count", "いいね数"


QUINTILE_LABELS = ["最低", "低", "中", "高", "最高"]


def _quantile_engagement(values: pd.Series, eng: pd.Series, min_count: int = 2) -> list:
    """
    連続値を5分位（最低/低/中/高/最高）に分け、帯ごとの平均エンゲージと件数を平均の降順で返す。
    データが少ない・値が偏って分割できない場合は空リスト。
    """
    work = pd.DataFrame({"_v": pd.to_numeric(values, errors="coerce"), "_e": eng}).dropna()
    if len(work) < 10:
        return []
    try:
        work["_band"] = pd.qcut(work["_v"], 5, labels=QUINTILE_LABELS, duplicates="drop")
    except Exception:
        return []
    work = work.dropna(subset=["_band"])
    if work["_band"].nunique() < 2:
        return []
    grp = (
        work.groupby("_band", observed=True)
        .agg(avg=("_e", "mean"), count=("_e", "count"))
        .reset_index()
    )
    grp = grp[grp["count"] >= min_count]
    if grp.empty:
        return []
    grp["band"] = grp["_band"].astype(str)
    grp = grp.sort_values("avg", ascending=False)
    return grp[["band", "avg", "count"]].round(2).to_dict("records")


def best_posting_slots(df_media: pd.DataFrame, top_n: int = 3, min_count: int = 3) -> list:
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


def top_hashtags_by_engagement(df_media: pd.DataFrame, top_n: int = 10, min_count: int = 3) -> list:
    """
    妻の投稿で、平均いいね数が高いハッシュタグ上位を返す（使用 min_count 回以上）。
    一度きりのイベント用タグ（#大分駅 など）が上位に来ないよう、既定は3回以上。

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
    grp = grp[grp["count"] >= min_count]
    if grp.empty:
        grp = (
            tags.groupby("hashtag")
            .agg(avg_like=("like_count", "mean"), count=("like_count", "count"))
            .reset_index()
        )
    grp = grp.sort_values("avg_like", ascending=False).head(top_n)
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


def _bin_engagement(
    df: pd.DataFrame, value_series: pd.Series, bins: list, labels: list, min_count: int = 3
) -> list:
    """
    値の区間ごとに平均エンゲージと件数を集計し、平均の降順で返す共通処理。
    件数が min_count 未満の区間は偶然に左右されるため除外する。
    """
    col = _engagement_col(df)
    work = pd.DataFrame(
        {"_v": value_series.values, "_eng": pd.to_numeric(df[col], errors="coerce").values}
    )
    work["_band"] = pd.cut(work["_v"], bins=bins, labels=labels, right=True)
    grp = (
        work.dropna(subset=["_band"])
        .groupby("_band", observed=True)
        .agg(avg=("_eng", "mean"), count=("_eng", "count"))
        .reset_index()
        .rename(columns={"_band": "band"})
    )
    grp = grp[grp["count"] >= min_count]
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


# この日数以上投稿が空いたら「停滞」として最優先で知らせる（週1〜2投稿が運用目標）
STALL_DAYS = 14


def posting_cadence(
    df_media: pd.DataFrame,
    recent_days: int = 30,
    baseline_days: int = 90,
    now: pd.Timestamp | None = None,
) -> dict:
    """
    投稿ペースを集計する。**基準は今日**（最後の投稿日ではない）。
    直近 recent_days の週あたり投稿数を、その前 baseline_days の週あたり投稿数と比べる。
    最終投稿からの経過日数 days_since_last も返す（投稿が止まると直近窓が空になり検知できる）。
    """
    if df_media.empty or "timestamp_jst" not in df_media.columns:
        return {}
    ts = pd.to_datetime(df_media["timestamp_jst"]).dropna().sort_values()
    if len(ts) < 2:
        return {}
    now = pd.Timestamp.now() if now is None else now
    recent_start = now - pd.Timedelta(days=recent_days)
    base_start = recent_start - pd.Timedelta(days=baseline_days)
    recent = ts[ts >= recent_start]
    baseline = ts[(ts >= base_start) & (ts < recent_start)]

    recent_per_week = round(len(recent) / (recent_days / 7), 2)
    older_per_week = round(len(baseline) / (baseline_days / 7), 2)
    # 平均投稿間隔（日）
    intervals = ts.diff().dropna().dt.total_seconds() / 86400
    avg_interval = round(float(intervals.mean()), 1) if not intervals.empty else None
    days_since_last = int((now - ts.max()).days)

    trend = "横ばい"
    if days_since_last >= STALL_DAYS:
        trend = "停滞"
    elif recent_per_week < older_per_week * 0.7:
        trend = "ペースダウン"
    elif older_per_week > 0 and recent_per_week > older_per_week * 1.3:
        trend = "ペースアップ"

    return {
        "recent_per_week": recent_per_week,
        "older_per_week": older_per_week,
        "avg_interval_days": avg_interval,
        "days_since_last": days_since_last,
        "last_post": ts.max(),
        "trend": trend,
        "recent_days": recent_days,
        "baseline_days": baseline_days,
    }


def low_performers(df_media: pd.DataFrame, bottom_n: int = 3, min_count: int = 3) -> dict:
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


def visual_engagement_analysis(df_media: pd.DataFrame) -> dict:
    """
    投稿画像の視覚特徴（collect_visual.py 由来）とエンゲージメントの関係を集計する。

    指標は保存率を優先（無ければエンゲージ率→いいね数）。連続特徴は5分位（最低/低/中/高/最高）の
    帯別平均、dominant_color はカテゴリ別平均をランキングで返す。視覚特徴が無ければ空 dict。

    Returns
    -------
    dict
        {
          "metric": 使用した指標列名, "metric_label": 日本語ラベル, "n": 対象投稿数,
          "features": {feature: {"label", "ranking":[{band,avg,count}], "best_band"}},
          "dominant_color": {"ranking":[{color,avg,count}], "best": color},
        }
    """
    if df_media.empty:
        return {}
    has_numeric = any(
        f in df_media.columns and df_media[f].notna().any() for f in VISUAL_NUMERIC_FEATURES
    )
    has_color = "dominant_color" in df_media.columns and df_media["dominant_color"].notna().any()
    if not has_numeric and not has_color:
        return {}

    metric, metric_label = _visual_engagement_col(df_media)
    eng = pd.to_numeric(df_media[metric], errors="coerce")
    # 視覚特徴を持つ行（数値特徴のいずれか or dominant_color が非欠損）
    has_visual = pd.Series(False, index=df_media.index)
    for f in list(VISUAL_NUMERIC_FEATURES) + ["dominant_color"]:
        if f in df_media.columns:
            has_visual = has_visual | df_media[f].notna()
    valid = eng.notna() & has_visual
    n = int(valid.sum())

    features = {}
    for feat, label in VISUAL_NUMERIC_FEATURES.items():
        if feat not in df_media.columns:
            continue
        ranking = _quantile_engagement(df_media.loc[valid, feat], eng[valid])
        if ranking:
            features[feat] = {"label": label, "ranking": ranking, "best_band": ranking[0]["band"]}

    color = {}
    if has_color:
        work = pd.DataFrame(
            {"color": df_media.loc[valid, "dominant_color"], "_e": eng[valid]}
        ).dropna()
        if not work.empty:
            grp = (
                work.groupby("color")
                .agg(avg=("_e", "mean"), count=("_e", "count"))
                .reset_index()
            )
            grp = grp[grp["count"] >= 2].sort_values("avg", ascending=False)
            if not grp.empty:
                ranking = grp.round(2).to_dict("records")
                color = {"ranking": ranking, "best": ranking[0]["color"]}

    if not features and not color:
        return {}
    return {
        "metric": metric,
        "metric_label": metric_label,
        "n": n,
        "features": features,
        "dominant_color": color,
    }


def actionable_advice(
    df_media: pd.DataFrame,
    df_cadence: pd.DataFrame = None,
) -> list:
    """
    ★各種統計を総合し、ルールベースで日本語の箇条書きアドバイスを生成する（AI不使用）。
    df_media は「今効く型」を見るため直近期間に絞ったもの（build_summary が recent_window で渡す）。
    df_cadence は投稿ペース判定用の全期間データ（省略時は df_media）。
    各助言は数値根拠付き。返り値は文字列のリスト。
    """
    if df_media.empty:
        return ["データがまだ少ないため、まずは投稿を続けてデータを貯めましょう。"]

    advice = []

    # ★ 投稿ペース（最優先）。止まっていると他の助言はどれも効かないため先頭に置く。
    #   基準は今日（posting_cadence）。停滞は全期間 df で判定する（窓で絞ると最終投稿を見失うため）。
    cad = posting_cadence(df_cadence if df_cadence is not None else df_media)
    if cad:
        if cad["trend"] == "停滞":
            advice.append(
                f"最後の投稿から{cad['days_since_last']}日空いています（目標は週1〜2件）。"
                "撮り溜めた作品写真か、制作途中の1枚だけでも投稿してペースを戻しましょう。"
            )
        elif cad["trend"] == "ペースダウン":
            advice.append(
                f"最近の投稿ペースが落ちています（直近{cad['recent_days']}日は週{cad['recent_per_week']}件、"
                f"その前は週{cad['older_per_week']}件）。ペースを戻すと露出が安定します。"
            )
        elif cad["trend"] == "ペースアップ":
            advice.append(
                f"投稿ペースが上がっています（直近は週{cad['recent_per_week']}件）。良い調子です。"
            )

    # 0. 発見→保存→プロフィール導線（インサイトがある場合の最優先助言）
    #    立ち上げ初期×作品販売/受注では、ファネル上流の「保存・リーチ・プロフィール訪問」を最重視する。
    if "reach" in df_media.columns and df_media["reach"].notna().any():
        ins = df_media[df_media["reach"].notna()]

        # 保存率（北極星指標）を上げる。全体平均はリーチ加重 Σ保存/Σリーチ で算出（低リーチ偏りを避ける）。
        if "saved" in ins.columns and ins["saved"].notna().any():
            _saved = pd.to_numeric(ins["saved"], errors="coerce")
            _reach = pd.to_numeric(ins["reach"], errors="coerce")
            _m = _saved.notna() & (_reach > 0)
            if _m.any() and _reach[_m].sum() > 0:
                mean_sr = float(_saved[_m].sum() / _reach[_m].sum() * 100)
                if mean_sr < 1.0:
                    advice.append(
                        f"保存率は平均{mean_sr:.2f}%（目安は1%超）。作品の制作背景やモチーフの物語を"
                        "キャプションに添え、「保存して見返してね」と一言入れると、おすすめ拡散の核となる"
                        "保存が伸びます。"
                    )
            # タイプ別比較は低リーチ補正済みの調整保存率を優先（無ければ生の保存率）
            sr_col = "saved_rate_adj" if "saved_rate_adj" in ins.columns and ins["saved_rate_adj"].notna().any() else "saved_rate"
            if sr_col in ins.columns and ins[sr_col].notna().any():
                sr_by_type = (
                    ins.dropna(subset=[sr_col])
                    .groupby("media_type")[sr_col]
                    .agg(["mean", "count"])
                )
                sr_by_type = sr_by_type[sr_by_type["count"] >= 2].sort_values("mean", ascending=False)
                if len(sr_by_type) >= 2:
                    top_t = sr_by_type.index[0]
                    advice.append(
                        f"保存率が最も高いのは「{MEDIA_TYPE_JA.get(top_t, top_t)}」"
                        f"（平均{sr_by_type.iloc[0]['mean']:.2f}%）。この型を増やすと保存が積み上がります。"
                    )

        # リール（動画）で新規の発見＝フォロワー外リーチを稼ぐ
        reach_by_type = ins.groupby("media_type")["reach"].mean()
        if "VIDEO" in reach_by_type.index and len(reach_by_type) >= 2:
            video_reach = float(reach_by_type["VIDEO"])
            other = ins[ins["media_type"] != "VIDEO"]["reach"]
            other_reach = float(other.mean()) if not other.empty else 0.0
            if other_reach > 0 and video_reach >= other_reach * 1.2:
                advice.append(
                    f"動画（リール）の平均リーチ{video_reach:,.0f}は静止画（{other_reach:,.0f}）より高めです。"
                    "制作過程・タイムラプスのリールを週1〜2本入れると新規の発見が増えます。"
                )

        # プロフィール訪問→販売・受注の導線整備
        if "profile_visits" in ins.columns and ins["profile_visits"].notna().any():
            # 平均はバズ投稿1件（PV2,000超）で大きく歪むため中央値を使う
            pv = float(ins["profile_visits"].median())
            if pv > 0:
                advice.append(
                    f"投稿1件でふだん{pv:,.0f}人ほどがプロフィールに来ています（中央値）。ハイライトに"
                    "「販売中／お問い合わせ／制作の流れ」を固定し、リンクと料金を明記すると受注につながります。"
                )

    # 0.5 写真の見え方（視覚特徴）→ 保存/エンゲージ。画像こそ作品アカウントの主役。
    va = visual_engagement_analysis(df_media)
    if va:
        label = va["metric_label"]
        # 帯間の差が最も大きく、方向（高/低）が明確な連続特徴を1つ選んで助言
        best = None
        for info in va.get("features", {}).values():
            rk = info["ranking"]
            top = rk[0]
            if top["band"] not in ("最高", "高", "低", "最低") or len(rk) < 2:
                continue
            lo = rk[-1]["avg"]
            if lo > 0 and top["avg"] >= lo * 1.2 and (best is None or top["avg"] / lo > best[0]):
                best = (top["avg"] / lo, info, top, rk[-1])
        if best:
            _, info, top, worst = best
            dir_word = "高め" if top["band"] in ("最高", "高") else "控えめ"
            advice.append(
                f"写真の傾向: 「{info['label']}」が{dir_word}の投稿ほど{label}が高めです"
                f"（{top['band']}={top['avg']} / {worst['band']}={worst['avg']}）。"
                "次の作品でこの方向を意識すると効果的です。"
            )
        dc = va.get("dominant_color") or {}
        if dc.get("ranking") and len(dc["ranking"]) >= 2:
            t = dc["ranking"][0]
            advice.append(
                f"主要色が「{t['color']}」系の作品は{label}が高めです"
                f"（平均{t['avg']}・{t['count']}件）。配色の参考に。"
            )

    # 1. 伸びるタイプを増やす提案（いいね基準。インサイトがあれば上の保存率基準の助言で足りるので出さない）
    has_reach = "reach" in df_media.columns and df_media["reach"].notna().any()
    types = best_media_type(df_media) if not has_reach else []
    if len(types) >= 2:
        best, worst = types[0], types[-1]
        total = sum(t["count"] for t in types)
        best_share = best["count"] / total if total else 0
        if best["avg_like"] >= worst["avg_like"] * 1.2 and best_share < 0.5:
            advice.append(
                f"「{best['type_ja']}」の平均いいねが{best['avg_like']}と高めですが投稿割合は"
                f"{best_share*100:.0f}%。{best['type_ja']}を増やすと伸びやすいです。"
            )

    metric_label = engagement_label(df_media)

    # 2. 最適な投稿タイミング
    slots = best_posting_slots(df_media)
    if slots:
        s = slots[0]
        advice.append(
            f"{s['day_name']}曜 {s['hour']}時台の投稿は{metric_label}が高めです（{s['count']}件）。"
            "次の投稿はこの時間帯を狙いましょう。"
        )

    # 3. ハッシュタグ数の最適化（0個推奨は避け、既に最適帯なら助言しない）
    hc = hashtag_count_analysis(df_media)
    if hc:
        target = hc.get("best_actionable_band")
        if target and hc.get("current_band") != target:
            advice.append(
                f"ハッシュタグは「{target}」の投稿で{metric_label}が最も高めです"
                f"（今の平均は{hc['current_avg']:.0f}個）。"
            )

    # 4. キャプション長の最適化（既に最適帯なら助言しない）
    cl = caption_length_analysis(df_media)
    if cl and cl.get("best_band") and cl.get("current_band") != cl["best_band"]:
        advice.append(
            f"キャプションは「{cl['best_band']}」の投稿で{metric_label}が最も高めです"
            f"（今の平均は{cl['current_avg']:.0f}字）。"
        )

    # 5. 効くタグの継続
    top_tags = top_hashtags_by_engagement(df_media, top_n=3)
    if top_tags:
        names = "　".join(f"#{t['hashtag']}" for t in top_tags)
        advice.append(f"反応が良いタグは継続を: {names}")

    return advice


# 月間4週サイクル（2026-07 合意の運用型。週1〜2投稿の制約内で販売まで回す）。
# (その週の最終日, テーマ, 具体的なヒント)。日付で今週のテーマを決める。
MONTHLY_CYCLE = [
    (7, "① 新作お披露目", "新作をスライド（カルーセル）で。全体→部分アップ→飾った様子の順に"),
    (14, "② 制作過程", "描いている途中・画材・こだわりを長めのキャプションで（保存されやすい）"),
    (21, "③ 抽選販売会", "販売できる作品があれば告知。告知は動画より静止画の方が届いた（2026-07実績）"),
    (31, "④ お迎え報告＋来月のカレンダー待受", "お迎え報告と、来月のスマホ用カレンダー待受（保存率トップ級の定番）"),
]


def this_week_actions(df_media: pd.DataFrame, now: pd.Timestamp | None = None) -> dict:
    """
    週次レポートとダッシュボードのホームで出す「今週やること」。
    月間4週サイクルの今週のテーマに、停滞・カレンダー待受の出し忘れの注意を添える。

    Returns
    -------
    dict
        {"theme": str, "hint": str, "notes": [str]}
    """
    now = pd.Timestamp.now() if now is None else now
    today = now.normalize()
    theme, hint = MONTHLY_CYCLE[-1][1], MONTHLY_CYCLE[-1][2]
    for last_day, t, h in MONTHLY_CYCLE:
        if today.day <= last_day:
            theme, hint = t, h
            break

    notes = []
    cad = posting_cadence(df_media, now=now)
    if cad and cad["days_since_last"] >= STALL_DAYS:
        notes.append(f"最後の投稿から{cad['days_since_last']}日空いています。まず1件出すのが最優先")
    # 22日以降、今月20日から「カレンダー」を含む投稿が無ければ来月分の待受を促す
    if today.day >= 22 and not df_media.empty and "caption" in df_media.columns:
        since = today.replace(day=20)
        recent = df_media[pd.to_datetime(df_media["timestamp_jst"]) >= since]
        if not recent["caption"].astype(str).str.contains("カレンダー").any():
            notes.append("来月のカレンダー待受がまだです（毎月の保存率トップ級）")
    return {"theme": theme, "hint": hint, "notes": notes}


def build_summary(
    df_media: pd.DataFrame,
    recent_months: int | None = RECENT_MONTHS,
) -> dict:
    """
    上記の統計をまとめて1つの辞書にする。dashboard表示・AIプロンプト両用。
    型・タイミング・タグ等の分析は直近 recent_months ヶ月に絞る（None で全期間）。
    """
    # 保存率の地合いは年々大きく変わる（2020→2026で約60倍低下）ため、型の分析は直近期間に絞る。
    # 投稿ペースだけは全期間 df で今日基準に判定する。
    df_recent = recent_window(df_media, recent_months)
    return {
        "best_slots": best_posting_slots(df_recent),
        "best_types": best_media_type(df_recent),
        "top_hashtags": top_hashtags_by_engagement(df_recent),
        "caption_length": caption_length_analysis(df_recent),
        "hashtag_count": hashtag_count_analysis(df_recent),
        "cadence": posting_cadence(df_media),
        "low_performers": low_performers(df_recent),
        "visual": visual_engagement_analysis(df_recent),
        "advice": actionable_advice(df_recent, df_cadence=df_media),
        "total_posts": int(len(df_media)),
        "metric_label": engagement_label(df_recent),
        "window_months": recent_months,
        "window_posts": int(len(df_recent)),
    }
