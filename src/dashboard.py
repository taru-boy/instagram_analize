import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import (DAY_JA, load_account_insights_data,
                         load_competitor_data, load_hashtag_data,
                         load_insights_data, load_media_data,
                         load_profile_data, merge_follower_at_post_date,
                         merge_insights)
from insights import build_summary

RESULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "result")

MEDIA_TYPE_JA = {"IMAGE": "画像", "CAROUSEL_ALBUM": "スライド", "VIDEO": "動画"}
MEDIA_TYPE_COLOR = {"IMAGE": "#E1306C", "CAROUSEL_ALBUM": "#833AB4", "VIDEO": "#F56040"}

# 保存率など「÷リーチ」系の比率ランキングで採用する最小リーチのパーセンタイル。
# 分母が極小だと比率がノイズ化し、リーチ1桁台の古い投稿が上位を占めるため除外する。
# 固定値ではなくパーセンタイルにすることで、アカウント成長に閾値が自動追従する。
REACH_PERCENTILE_FOR_RATE = 0.75

st.set_page_config(
    page_title="Instagram 分析ダッシュボード",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stMetric"] {
    background: #fafafa;
    border: 1px solid #efefef;
    border-radius: 10px;
    padding: 14px 18px;
}
[data-testid="stMetricValue"] { font-size: 1.6rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load_all_data():
    df_profile = load_profile_data(RESULT_DIR)
    df_media = load_media_data(RESULT_DIR)
    if not df_media.empty and not df_profile.empty:
        df_media = merge_follower_at_post_date(df_media, df_profile)
    # インサイト（リーチ・保存・シェアなど）を id で結合
    df_insights = load_insights_data(RESULT_DIR)
    if not df_media.empty:
        df_media = merge_insights(df_media, df_insights)
    df_account_insights = load_account_insights_data(RESULT_DIR)
    df_competitors = load_competitor_data(RESULT_DIR)
    df_hashtags = load_hashtag_data(RESULT_DIR)
    return df_profile, df_media, df_competitors, df_hashtags, df_account_insights


df_profile, df_media, df_competitors, df_hashtags, df_account_insights = load_all_data()

# インサイト列が存在し、かつ実データがあるか
HAS_INSIGHTS = (
    not df_media.empty
    and "reach" in df_media.columns
    and df_media["reach"].notna().any()
)

# -------- サイドバー --------
with st.sidebar:
    st.title("🎨 フィルター")

    if not df_media.empty:
        min_d = df_media["post_date"].min().date()
        max_d = df_media["post_date"].max().date()
        date_range = st.date_input("投稿期間", value=(min_d, max_d), min_value=min_d, max_value=max_d)

        all_types = sorted(df_media["media_type"].dropna().unique().tolist())
        type_labels = [MEDIA_TYPE_JA.get(t, t) for t in all_types]
        selected_labels = st.multiselect("投稿タイプ", options=type_labels, default=type_labels)
        selected_types = [t for t, l in zip(all_types, type_labels) if l in selected_labels]
    else:
        date_range = ()
        selected_types = []

    st.divider()
    st.caption("同じWiFiのスマホから\nアクセスできます 📱")

# -------- フィルタリング --------
if not df_media.empty and len(date_range) == 2:
    s_date, e_date = date_range
    df_f = df_media[
        (df_media["post_date"].dt.date >= s_date)
        & (df_media["post_date"].dt.date <= e_date)
        & (df_media["media_type"].isin(selected_types))
    ].copy()
else:
    df_f = df_media.copy()

# -------- ページタイトル --------
st.title("🎨 Instagram 分析")
if not df_profile.empty:
    latest_date = df_profile["date"].iloc[-1].strftime("%Y年%m月%d日")
    st.caption(f"最終更新: {latest_date}　|　総投稿数: {len(df_media):,}件")

if df_profile.empty and df_media.empty:
    st.error("データが見つかりませんでした。result/ フォルダを確認してください。")
    st.stop()

# -------- KPIカード --------
# 立ち上げ初期×作品販売/受注の方針に合わせ、ファネル上流
# （発見→保存→プロフィール訪問→フォロー転換）を主役KPIに据える。
# 上段は「直近30日の平均＋前30日比」に固定した“今の体調メーター”で、サイドバーの
# 投稿期間フィルターには連動しない（フィルターは下段の詳細・投稿一覧専用）。


def _window_slice(df, anchor, days=30, offset=0):
    """anchor を基準に (anchor-(offset+days)日, anchor-offset日] の投稿を返す。
    offset=0 で直近days日、offset=days で1つ前のdays日。"""
    if df.empty or "post_date" not in df.columns:
        return df.iloc[0:0]
    end = anchor - pd.Timedelta(days=offset)
    start = anchor - pd.Timedelta(days=offset + days)
    return df[(df["post_date"] > start) & (df["post_date"] <= end)]


def _window_rate(df, num_col, den_col="reach"):
    """リーチ加重の比率 sum(num)/sum(den)*100 と対象件数を返す。
    分母（リーチ）が極小の投稿に引っ張られないよう、平均ではなく合計同士で割る。
    算出不能なら (None, 0)。"""
    if df.empty or num_col not in df.columns or den_col not in df.columns:
        return None, 0
    num = pd.to_numeric(df[num_col], errors="coerce")
    den = pd.to_numeric(df[den_col], errors="coerce")
    mask = num.notna() & den.notna() & (den > 0)
    n = int(mask.sum())
    total_den = den[mask].sum()
    if n == 0 or total_den <= 0:
        return None, 0
    return float(num[mask].sum() / total_den * 100), n


def _window_engagement_rate(df):
    """リーチ加重のエンゲージ率 sum(いいね+コメント)/sum(reach)*100 と件数。"""
    if df.empty or "reach" not in df.columns:
        return None, 0
    reach = pd.to_numeric(df["reach"], errors="coerce")
    inter = (
        pd.to_numeric(df.get("like_count"), errors="coerce").fillna(0)
        + pd.to_numeric(df.get("comments_count"), errors="coerce").fillna(0)
    )
    mask = reach.notna() & (reach > 0)
    n = int(mask.sum())
    total = reach[mask].sum()
    if n == 0 or total <= 0:
        return None, 0
    return float(inter[mask].sum() / total * 100), n


def _window_mean(df, col):
    """窓内の col の平均と件数を返す。算出不能なら (None, 0)。"""
    if df.empty or col not in df.columns:
        return None, 0
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return None, 0
    return float(s.mean()), int(len(s))


def _fmt_delta(recent, prev, kind):
    """前30日比デルタ文字列。prev/recent が None ならデルタ非表示(None)。
    kind: 'pt'（率=パーセントポイント）/ 'int'（件数）/ 'float1'（小数1桁）。
    st.metric は先頭が '-' なら赤・それ以外は緑で色付けする（全KPI高いほど良い）。"""
    if recent is None or prev is None:
        return None
    d = recent - prev
    if kind == "pt":
        return f"{d:+.1f}pt"
    if kind == "int":
        return f"{d:+,.0f}"
    return f"{d:+,.1f}"


def _followers_at(df_profile, when):
    """when 以前で最新のフォロワー数を返す。無ければ None。"""
    sub = df_profile[df_profile["date"] <= when]
    return int(sub["followers_count"].iloc[-1]) if not sub.empty else None


# 直近30日 / 前30日の投稿窓（実時間基準。投稿が止まればその月の件数が減る＝正しいシグナル）
_now = pd.Timestamp.now().normalize()
win_recent = _window_slice(df_media, _now, days=30, offset=0)
win_prev = _window_slice(df_media, _now, days=30, offset=30)

# 各KPIの直近30日値・前30日値（比率はリーチ加重、件数は平均）
sr_now, n_recent = _window_rate(win_recent, "saved", "reach")
sr_prev, _ = _window_rate(win_prev, "saved", "reach")
reach_now, _ = _window_mean(win_recent, "reach")
reach_prev, _ = _window_mean(win_prev, "reach")
pv_now, _ = _window_mean(win_recent, "profile_visits")
pv_prev, _ = _window_mean(win_prev, "profile_visits")
nf_now, _ = _window_rate(win_recent, "reach_non_follower", "reach")
nf_prev, _ = _window_rate(win_prev, "reach_non_follower", "reach")
eng_now, _ = _window_engagement_rate(win_recent)
eng_prev, _ = _window_engagement_rate(win_prev)
sh_now, _ = _window_mean(win_recent, "shares")
sh_prev, _ = _window_mean(win_prev, "shares")
n_prev = len(win_prev)

# フォロワー純増（直近30日の純増。デルタは前30日の純増との差）
latest_followers = None
gain_now = None
gain_prev = None
if not df_profile.empty:
    latest_followers = int(df_profile["followers_count"].iloc[-1])
    p_now = df_profile["date"].iloc[-1]
    f_now = latest_followers
    f_30 = _followers_at(df_profile, p_now - pd.Timedelta(days=30))
    f_60 = _followers_at(df_profile, p_now - pd.Timedelta(days=60))
    if f_30 is None:  # 履歴が浅い場合は最古値で代替
        f_30 = int(df_profile["followers_count"].iloc[0])
    gain_now = f_now - f_30
    if f_60 is not None:
        gain_prev = f_30 - f_60


def _val(x, fmt):
    """値が None なら '—'、そうでなければ fmt で整形。"""
    return "—" if x is None else fmt(x)


# === 1段目: 直近30日の重視KPI（前30日比） ===
st.markdown("##### 🎯 直近30日の重視KPI（前30日比）　— 発見 → 保存 → プロフィール訪問 → フォロー")
k1, k2, k3, k4 = st.columns(4)

# 🔖 保存率（リーチ加重。北極星: 作品が刺さったか）
k1.metric(
    "🔖 保存率", _val(sr_now, lambda v: f"{v:.2f}%"),
    delta=_fmt_delta(sr_now, sr_prev, "pt"),
    help="保存数の合計 ÷ リーチの合計（リーチ加重）。作品が刺さった最良のシグナルで、おすすめ拡散の核。1%超で優秀。"
         if HAS_INSIGHTS else "`python src/collect_insights.py` でインサイトを収集すると表示されます",
)

# 👀 平均リーチ（発見: 1投稿が届いた人数）
k2.metric(
    "👀 平均リーチ", _val(reach_now, lambda v: f"{v:,.0f}"),
    delta=_fmt_delta(reach_now, reach_prev, "int"),
    help="1投稿が届いた人数の平均。リール・保存・シェアで新規の発見が増えます。",
)

# 🏠 平均プロフィール訪問（販売・受注の入口）
k3.metric(
    "🏠 平均プロフィール訪問", _val(pv_now, lambda v: f"{v:,.1f}"),
    delta=_fmt_delta(pv_now, pv_prev, "float1"),
    help="投稿を見てプロフィールに来た数（投稿あたり平均）。販売・受注の入口。",
)

# 📈 フォロワー純増（フォロー転換の代理指標）
k4.metric(
    "📈 フォロワー純増", _val(gain_now, lambda v: f"{v:+,}"),
    delta=_fmt_delta(gain_now, gain_prev, "int"),
    help="直近30日のフォロワー純増。プロフィール訪問→フォロー転換の代理指標。デルタは前30日の純増との差。",
)

# === 2段目: 補助KPI ===
s1, s2, s3, s4 = st.columns(4)

# 🆕 フォロワー外リーチ比率（リーチ加重。発見＝新規との出会い）
s1.metric(
    "🆕 フォロワー外リーチ比率", _val(nf_now, lambda v: f"{v:.0f}%"),
    delta=_fmt_delta(nf_now, nf_prev, "pt"),
    help="フォロワー以外に届いたリーチの割合（リーチ加重）。発見＝新規との出会いの指標。リールで伸ばせます。",
)

# 👥 フォロワー数（最新・時点値）
s2.metric("👥 フォロワー数", _val(latest_followers, lambda v: f"{v:,}"))

# 💬 エンゲージ率（リーチ加重・直近30日）
s3.metric(
    "💬 エンゲージ率（リーチ基準）", _val(eng_now, lambda v: f"{v:.2f}%"),
    delta=_fmt_delta(eng_now, eng_prev, "pt"),
    help="(いいね＋コメント) の合計 ÷ リーチの合計。届いた人のうち反応した割合。",
)

# 🔁 平均シェア数（リーチ拡大の二次エンジン）
s4.metric(
    "🔁 平均シェア数", _val(sh_now, lambda v: f"{v:,.1f}"),
    delta=_fmt_delta(sh_now, sh_prev, "float1"),
    help="ストーリーズ/DMでの共有（投稿あたり平均）。保存と並ぶリーチ拡大の二次エンジン。",
)

# 集計範囲とアカウント全体インサイト（販売導線の最終指標）の補足
st.caption(
    f"※ 上段KPIは**直近30日**の投稿 {n_recent} 件（前30日は {n_prev} 件）から算出・前30日比。"
    "比率はリーチ加重。フォロワー純増は最新−30日前。サイドバーの期間フィルターは下段にのみ効きます。"
)
if not df_account_insights.empty:
    last = df_account_insights.iloc[-1]
    st.caption(
        f"🔗 直近のアカウント全体: プロフィールアクセス {int(last['profile_views']):,} ／ "
        f"リンククリック {int(last['website_clicks'])} 回（{last['date'].strftime('%m月%d日')}時点・販売導線の最終指標）"
    )
if not HAS_INSIGHTS:
    st.caption(
        "💡 `python src/collect_insights.py` でリーチ・保存・プロフィール訪問を収集すると、"
        "上段の重視KPI（保存率・リーチ・プロフィール訪問など）が表示されます。"
    )
elif n_recent == 0:
    st.caption(
        "⚠️ 直近30日にインサイト付きの投稿がありません。`python src/collect_insights.py` でインサイトを更新してください。"
    )

st.divider()

# -------- Section 1: フォロワー推移 --------
st.subheader("📈 フォロワー推移")

if not df_profile.empty:
    fig = px.line(
        df_profile,
        x="date",
        y="followers_count",
        labels={"date": "日付", "followers_count": "フォロワー数"},
        markers=True,
    )
    fig.update_traces(line_color="#E1306C", marker_color="#E1306C", marker_size=5)
    fig.update_layout(
        plot_bgcolor="white",
        hovermode="x unified",
        yaxis=dict(gridcolor="#f5f5f5"),
        xaxis=dict(gridcolor="#f5f5f5"),
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("プロフィールデータがまだありません")

st.divider()

# -------- Section 2: 投稿パフォーマンス一覧 --------
st.subheader("🏆 投稿パフォーマンス一覧")
st.caption(
    "📊＝総エンゲージ率（いいね＋コメント＋**保存＋シェア** ÷ 投稿時点フォロワー）。"
    "保存・シェアはインサイトのある投稿でのみ加算され、未取得の古い投稿はいいね＋コメントで算出します。"
)

if not df_f.empty:
    ctrl_l, ctrl_r = st.columns([3, 1])
    with ctrl_l:
        # 保存率（保存数÷リーチ）はリーチが小さい昔の投稿ほど高く出る構造的バイアスがあり、
        # 時代をまたいだ比較に向かない。代わりに絶対「保存数」を既定の並び順にする。
        if HAS_INSIGHTS:
            sort_options = {
                "saved": "🔖 保存数が多い順",
                "reach": "👀 リーチが多い順",
                "shares": "🔁 シェア数が多い順",
                "saved_rate": "🔖 保存率が高い順（参考・リーチ小に偏りやすい）",
                "like_count": "❤️ いいね数が多い順",
                "comments_count": "💬 コメント数が多い順",
                "total_engagement_rate": "📊 エンゲージ率（保存・シェア込）が高い順",
                "timestamp_jst": "🕐 新しい投稿順",
            }
        else:
            sort_options = {
                "like_count": "❤️ いいね数が多い順",
                "comments_count": "💬 コメント数が多い順",
                "engagement_rate": "📊 エンゲージメント率が高い順",
                "timestamp_jst": "🕐 新しい投稿順",
            }
        # 実際に存在する列だけに絞る（キャッシュが古く列が無くても KeyError にしない）
        sort_options = {k: v for k, v in sort_options.items() if k in df_f.columns}
        sort_col = st.selectbox(
            "並べ替え",
            options=list(sort_options.keys()),
            format_func=lambda x: sort_options[x],
        )
    with ctrl_r:
        n_show = st.select_slider("表示件数", options=[6, 9, 12, 18, 24, 30], value=12)

    # 保存率で並べる場合は、分母（リーチ）が極小なノイズ投稿を保存率ランキングと同じ基準で除外する
    df_to_sort = df_f
    if sort_col == "saved_rate" and "reach" in df_f.columns and df_f["reach"].notna().any():
        reach_floor = df_f["reach"].quantile(REACH_PERCENTILE_FOR_RATE)
        pct_label = int(round((1 - REACH_PERCENTILE_FOR_RATE) * 100))
        df_to_sort = df_f[df_f["reach"] >= reach_floor]
        st.caption(f"保存率順はリーチ上位{pct_label}%（{reach_floor:.0f}以上）の投稿のみを対象にしています（分母が小さい古い投稿を除外）。")

    df_sorted = df_to_sort.sort_values(sort_col, ascending=False, na_position="last")
    posts = df_sorted.head(n_show).reset_index(drop=True)

    for i in range(0, len(posts), 5):
        cols = st.columns(5)
        for j in range(5):
            idx = i + j
            if idx >= len(posts):
                break
            row = posts.iloc[idx]
            with cols[j]:
                url = str(row.get("media_url", ""))
                if url.startswith("http"):
                    st.image(url, use_container_width=True)
                else:
                    st.markdown("🖼️ *画像なし*")

                date_str = row["timestamp_jst"].strftime("%Y/%m/%d")
                type_ja = MEDIA_TYPE_JA.get(row["media_type"], row["media_type"])
                st.markdown(f"**{date_str}**　`{type_ja}`")

                # 総エンゲージ率（保存・シェア込）を優先表示。無ければ基本ERにフォールバック
                eng_val = row.get("total_engagement_rate")
                if pd.isna(eng_val):
                    eng_val = row.get("engagement_rate")
                eng_str = f"　📊 {eng_val:.1f}%" if pd.notna(eng_val) else ""
                st.caption(f"❤️ {int(row['like_count']):,}　💬 {int(row['comments_count']):,}{eng_str}")

                # インサイトがあれば2行目に表示
                if HAS_INSIGHTS and pd.notna(row.get("reach")):
                    ins_parts = [f"👀 {int(row['reach']):,}", f"🔖 {int(row['saved'])}", f"🔁 {int(row['shares'])}"]
                    if pd.notna(row.get("views")):
                        ins_parts.append(f"▶️ {int(row['views']):,}")
                    st.caption("　".join(ins_parts))

    st.caption("※ Instagram のCDN画像は有効期限があります。古い投稿は表示されない場合があります。")
else:
    st.info("フィルター条件に合う投稿がありません")

st.divider()

# -------- Section 3: エンゲージメント分析 --------
st.subheader("💡 エンゲージメント分析")

if not df_f.empty:
    tab1, tab2, tab3 = st.tabs(["📊 時系列", "🗓️ 投稿タイミング", "📸 タイプ別比較"])

    with tab1:
        if "engagement_rate" in df_f.columns:
            df_scatter = df_f.copy()
            df_scatter["type_ja"] = df_scatter["media_type"].map(MEDIA_TYPE_JA).fillna(df_scatter["media_type"])
            # 縦軸: エンゲージメント数（いいね＋コメント）
            df_scatter["engagement_count"] = df_scatter["like_count"] + df_scatter["comments_count"]
            # バブルの大きさ: エンゲージメント率（負・NaNは0に）
            df_scatter["size_val"] = df_scatter["engagement_rate"].fillna(0).clip(lower=0)
            fig2 = px.scatter(
                df_scatter,
                x="timestamp_jst",
                y="engagement_count",
                color="type_ja",
                size="size_val",
                size_max=25,
                hover_data={
                    "like_count": True,
                    "comments_count": True,
                    "engagement_rate": True,
                    "size_val": False,
                    "type_ja": False,
                },
                labels={
                    "timestamp_jst": "投稿日時",
                    "engagement_count": "エンゲージメント数（いいね＋コメント）",
                    "engagement_rate": "エンゲージメント率 (%)",
                    "type_ja": "タイプ",
                    "like_count": "いいね数",
                    "comments_count": "コメント数",
                },
                color_discrete_map={v: MEDIA_TYPE_COLOR[k] for k, v in MEDIA_TYPE_JA.items()},
            )
            fig2.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#f5f5f5"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig2, use_container_width=True)
            st.caption("縦軸 = エンゲージメント数（いいね＋コメント）　円の大きさ = エンゲージメント率")
        else:
            st.info("エンゲージメント率データがありません")

    with tab2:
        st.markdown("**曜日・時間帯別の平均いいね数**（投稿が多い時間帯を知る）")
        pivot = df_f.pivot_table(values="like_count", index="day_name", columns="hour", aggfunc="mean")
        pivot = pivot.reindex([d for d in DAY_JA if d in pivot.index])
        pivot.columns = [f"{h}時" for h in pivot.columns]

        fig3 = px.imshow(
            pivot,
            labels={"x": "時間帯 (JST)", "y": "曜日", "color": "平均いいね数"},
            color_continuous_scale="RdPu",
            aspect="auto",
        )
        fig3.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("※ 投稿数が少ない時間帯は参考程度にご覧ください")

    with tab3:
        type_stats = (
            df_f.groupby("media_type")
            .agg(平均いいね数=("like_count", "mean"), 平均コメント数=("comments_count", "mean"), 投稿数=("like_count", "count"))
            .reset_index()
        )
        type_stats["タイプ"] = type_stats["media_type"].map(MEDIA_TYPE_JA).fillna(type_stats["media_type"])
        type_stats["平均いいね数"] = type_stats["平均いいね数"].round(1)
        type_stats["平均コメント数"] = type_stats["平均コメント数"].round(1)

        col_a, col_b = st.columns(2)
        with col_a:
            fig4 = px.bar(
                type_stats,
                x="タイプ",
                y="平均いいね数",
                text="平均いいね数",
                color="タイプ",
                color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()),
                title="タイプ別 平均いいね数",
            )
            fig4.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            fig4.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig4, use_container_width=True)

        with col_b:
            fig5 = px.bar(
                type_stats,
                x="タイプ",
                y="投稿数",
                text="投稿数",
                color="タイプ",
                color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()),
                title="タイプ別 投稿数",
            )
            fig5.update_traces(texttemplate="%{text}", textposition="outside")
            fig5.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig5, use_container_width=True)

st.divider()

# -------- Section 3.5: リーチ・保存分析（インサイトがある場合のみ） --------
if HAS_INSIGHTS:
    df_ri = df_f[df_f["reach"].notna()].copy() if "reach" in df_f.columns else pd.DataFrame()
    if not df_ri.empty:
        st.subheader("👀 リーチ・保存分析")
        st.caption("インサイト取得済みの投稿のみが対象です。")

        tab_labels = ["📈 リーチ推移", "🔖 保存数ランキング", "📸 タイプ別リーチ"]
        has_nf = "non_follower_reach_rate" in df_ri.columns and df_ri["non_follower_reach_rate"].notna().any()
        if has_nf:
            tab_labels.append("🆕 フォロワー外リーチ")
        tabs_r = st.tabs(tab_labels)
        tab_r1, tab_r2, tab_r3 = tabs_r[0], tabs_r[1], tabs_r[2]
        tab_r4 = tabs_r[3] if has_nf else None

        with tab_r1:
            df_ri_sorted = df_ri.sort_values("timestamp_jst")
            df_ri_sorted["type_ja"] = df_ri_sorted["media_type"].map(MEDIA_TYPE_JA).fillna(df_ri_sorted["media_type"])
            fig_r = px.bar(
                df_ri_sorted,
                x="timestamp_jst",
                y="reach",
                color="type_ja",
                labels={"timestamp_jst": "投稿日時", "reach": "リーチ数", "type_ja": "タイプ"},
                color_discrete_map={v: MEDIA_TYPE_COLOR[k] for k, v in MEDIA_TYPE_JA.items()},
            )
            fig_r.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#f5f5f5"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_r, use_container_width=True)

        with tab_r2:
            # 保存率（保存数÷リーチ）はリーチが小さい昔の投稿ほど高く出る構造的バイアスがあるため、
            # 絶対「保存数」でランキングする（保存率は参考列として併記）。
            st.markdown(
                "**保存数が多い投稿 TOP10**　— 保存される＝あとで見返したい良コンテンツ"
                "（保存率は分母のリーチが小さい昔の投稿ほど高く出るため、件数そのもので評価）"
            )
            top_saved = (
                df_ri[df_ri["saved"].notna()]
                .sort_values("saved", ascending=False)
                .head(10)
            )
            if not top_saved.empty:
                disp = top_saved[["timestamp_jst", "media_type", "reach", "saved", "saved_rate", "like_count"]].copy()
                disp["timestamp_jst"] = disp["timestamp_jst"].dt.strftime("%Y/%m/%d")
                disp["media_type"] = disp["media_type"].map(MEDIA_TYPE_JA).fillna(disp["media_type"])
                disp.columns = ["投稿日", "タイプ", "リーチ", "保存数", "保存率(%)", "いいね"]
                st.dataframe(disp, use_container_width=True, hide_index=True)
            else:
                st.info("保存数データがありません")

        with tab_r3:
            type_ins = (
                df_ri.groupby("media_type")
                .agg(平均リーチ=("reach", "mean"), 平均保存数=("saved", "mean"), 投稿数=("reach", "count"))
                .reset_index()
            )
            type_ins["タイプ"] = type_ins["media_type"].map(MEDIA_TYPE_JA).fillna(type_ins["media_type"])
            type_ins["平均リーチ"] = type_ins["平均リーチ"].round(0)
            type_ins["平均保存数"] = type_ins["平均保存数"].round(1)
            col_ra, col_rb = st.columns(2)
            with col_ra:
                fig_ra = px.bar(
                    type_ins, x="タイプ", y="平均リーチ", text="平均リーチ", color="タイプ",
                    color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()), title="タイプ別 平均リーチ",
                )
                fig_ra.update_traces(texttemplate="%{text:.0f}", textposition="outside")
                fig_ra.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_ra, use_container_width=True)
            with col_rb:
                fig_rb = px.bar(
                    type_ins, x="タイプ", y="平均保存数", text="平均保存数", color="タイプ",
                    color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()), title="タイプ別 平均保存数",
                )
                fig_rb.update_traces(texttemplate="%{text:.1f}", textposition="outside")
                fig_rb.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_rb, use_container_width=True)

        if tab_r4 is not None:
            with tab_r4:
                st.markdown(
                    "**フォロワー外リーチ比率の推移**　— 新規（フォロワー以外）にどれだけ届いたか。"
                    "立ち上げ初期は、この比率を高く保つことが発見＝新規フォロワー獲得につながります。"
                )
                df_nf = df_ri[df_ri["non_follower_reach_rate"].notna()].sort_values("timestamp_jst").copy()
                df_nf["type_ja"] = df_nf["media_type"].map(MEDIA_TYPE_JA).fillna(df_nf["media_type"])
                fig_nf = px.bar(
                    df_nf,
                    x="timestamp_jst",
                    y="non_follower_reach_rate",
                    color="type_ja",
                    labels={
                        "timestamp_jst": "投稿日時",
                        "non_follower_reach_rate": "フォロワー外リーチ比率 (%)",
                        "type_ja": "タイプ",
                    },
                    color_discrete_map={v: MEDIA_TYPE_COLOR[k] for k, v in MEDIA_TYPE_JA.items()},
                )
                fig_nf.update_layout(
                    plot_bgcolor="white", yaxis=dict(gridcolor="#f5f5f5"),
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig_nf, use_container_width=True)
                avg_nf = df_nf["non_follower_reach_rate"].mean()
                # フォロワー外リーチ比率が高い投稿 TOP5（何が新規に届いたかの手がかり）
                top_nf = df_nf.sort_values("non_follower_reach_rate", ascending=False).head(5)
                st.caption(f"平均フォロワー外リーチ比率: {avg_nf:.1f}%")
                disp_nf = top_nf[["timestamp_jst", "media_type", "reach", "reach_non_follower", "non_follower_reach_rate"]].copy()
                disp_nf["timestamp_jst"] = disp_nf["timestamp_jst"].dt.strftime("%Y/%m/%d")
                disp_nf["media_type"] = disp_nf["media_type"].map(MEDIA_TYPE_JA).fillna(disp_nf["media_type"])
                disp_nf.columns = ["投稿日", "タイプ", "リーチ", "うち新規", "新規比率(%)"]
                st.markdown("**新規に最も届いた投稿 TOP5**")
                st.dataframe(disp_nf, use_container_width=True, hide_index=True)

        st.divider()

# -------- Section 4: ハッシュタグ分析 --------
st.subheader("🔖 ハッシュタグ分析")

if not df_f.empty and "hashtag" in df_f.columns:
    hashtag_rows = []
    for _, row in df_f.iterrows():
        if pd.isna(row["hashtag"]) or str(row["hashtag"]).strip() == "":
            continue
        for tag in str(row["hashtag"]).split("\n"):
            tag = tag.strip()
            if tag:
                hashtag_rows.append({"hashtag": f"#{tag}", "like_count": row["like_count"]})

    if hashtag_rows:
        df_tags = pd.DataFrame(hashtag_rows)
        tab_h1, tab_h2 = st.tabs(["❤️ いいねが多いタグ TOP20", "📊 よく使うタグ TOP20"])

        with tab_h1:
            top_likes = (
                df_tags.groupby("hashtag")["like_count"]
                .mean()
                .reset_index()
                .sort_values("like_count", ascending=False)
                .head(20)
            )
            top_likes.columns = ["ハッシュタグ", "平均いいね数"]
            top_likes["平均いいね数"] = top_likes["平均いいね数"].round(1)
            fig6 = px.bar(
                top_likes.iloc[::-1],
                x="平均いいね数",
                y="ハッシュタグ",
                orientation="h",
                color="平均いいね数",
                color_continuous_scale="RdPu",
            )
            fig6.update_layout(plot_bgcolor="white", coloraxis_showscale=False, height=520, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig6, use_container_width=True)

        with tab_h2:
            freq = df_tags["hashtag"].value_counts().reset_index().head(20)
            freq.columns = ["ハッシュタグ", "使用回数"]
            fig7 = px.bar(
                freq.iloc[::-1],
                x="使用回数",
                y="ハッシュタグ",
                orientation="h",
                color="使用回数",
                color_continuous_scale="PuRd",
            )
            fig7.update_layout(plot_bgcolor="white", coloraxis_showscale=False, height=520, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig7, use_container_width=True)
    else:
        st.info("ハッシュタグデータがありません")

st.divider()

# -------- Section 5: 投稿提案 --------
st.subheader("💡 投稿提案")

PRED_COLOR = {"高": "#E1306C", "中": "#F56040", "低": "#9e9e9e"}

# 「伸びる条件」は全期間データから算出（フィルタの影響を受けない）
summary = build_summary(df_media, df_competitors, df_hashtags)

# 📋 次にやるべきこと（統計から自動生成・無料）
st.markdown("##### 📋 次にやるべきこと")
advice = summary.get("advice", [])
if advice:
    with st.container(border=True):
        for a in advice:
            st.markdown(f"- {a}")
    st.caption("※ すべて過去データの数値根拠にもとづく提案です（AI不使用・無料）")
else:
    st.info("データが貯まるとここに具体的な提案が表示されます")

st.markdown("##### 📌 データから見た「伸びる条件」")
sc1, sc2, sc3 = st.columns(3)

with sc1:
    if summary["best_slots"]:
        s = summary["best_slots"][0]
        st.metric("⏰ 反応が良い投稿タイミング", f"{s['day_name']}曜 {s['hour']}時台")
        others = "　".join(
            f"{x['day_name']}曜{x['hour']}時" for x in summary["best_slots"][1:3]
        )
        if others:
            st.caption(f"次点: {others}")
    else:
        st.metric("⏰ 反応が良い投稿タイミング", "—")

with sc2:
    if summary["best_types"]:
        t = summary["best_types"][0]
        st.metric("📸 伸びる投稿タイプ", t["type_ja"])
        st.caption(f"平均いいね {t['avg_like']}（{t['count']}件）")
    else:
        st.metric("📸 伸びる投稿タイプ", "—")

with sc3:
    if summary["top_hashtags"]:
        tags = "　".join(f"#{h['hashtag']}" for h in summary["top_hashtags"][:5])
        st.metric("🔖 効くハッシュタグ", f"{len(summary['top_hashtags'])}個")
        st.caption(tags)
    else:
        st.metric("🔖 効くハッシュタグ", "—")

if summary["trending_topics"]:
    trend_tags = "　".join(
        f"#{t['hashtag']}" for t in summary["trending_topics"][:10]
    )
    st.markdown(f"**🌐 業界トレンド（競合・人気タグ投稿で多用）**\n\n{trend_tags}")
else:
    st.caption(
        "💡 競合・ハッシュタグのトレンドデータを集めると、より精度の高い提案ができます"
        "（`python src/collect_competitors.py` / `python src/collect_hashtags.py`）"
    )

# 📐 投稿の型（キャプション長・タグ数・投稿ペース）
st.markdown("##### 📐 伸びる投稿の「型」")
cl = summary.get("caption_length") or {}
hc = summary.get("hashtag_count") or {}
cad = summary.get("cadence") or {}

tc1, tc2, tc3 = st.columns(3)
with tc1:
    if cl:
        st.metric("✍️ 伸びるキャプション長", cl.get("best_band", "—"))
        st.caption(f"今の平均: {cl.get('current_avg', '—')}字")
    else:
        st.metric("✍️ 伸びるキャプション長", "—")
with tc2:
    if hc:
        st.metric("🔢 伸びるハッシュタグ数", hc.get("best_actionable_band", "—"))
        st.caption(f"今の平均: {hc.get('current_avg', '—')}個")
    else:
        st.metric("🔢 伸びるハッシュタグ数", "—")
with tc3:
    if cad:
        st.metric("🗓️ 最近の投稿ペース", f"週 {cad.get('recent_per_week', '—')}件")
        trend = cad.get("trend", "")
        prev = cad.get("older_per_week")
        st.caption(f"傾向: {trend}" + (f"（以前は週{prev}件）" if prev else ""))
    else:
        st.metric("🗓️ 最近の投稿ペース", "—")

detail_l, detail_r = st.columns(2)
with detail_l:
    if cl.get("ranking"):
        dfc = pd.DataFrame(cl["ranking"])
        fig_cl = px.bar(
            dfc, x="band", y="avg",
            labels={"band": "キャプション長", "avg": "平均エンゲージ"},
            title="キャプション長 × 反応",
        )
        fig_cl.update_traces(marker_color="#833AB4")
        fig_cl.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0), height=300)
        st.plotly_chart(fig_cl, use_container_width=True)
with detail_r:
    if hc.get("ranking"):
        dfh = pd.DataFrame(hc["ranking"])
        fig_hc = px.bar(
            dfh, x="band", y="avg",
            labels={"band": "ハッシュタグ数", "avg": "平均エンゲージ"},
            title="ハッシュタグ数 × 反応",
        )
        fig_hc.update_traces(marker_color="#E1306C")
        fig_hc.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0), height=300)
        st.plotly_chart(fig_hc, use_container_width=True)

# ⚠️ 避けたい条件
low = summary.get("low_performers") or {}
if low.get("worst_slots") or low.get("worst_type"):
    with st.expander("⚠️ 避けたい条件（反応が低かったパターン）"):
        if low.get("worst_type"):
            wt = low["worst_type"]
            st.markdown(
                f"- 最も伸びにくいタイプ: **{wt['type_ja']}**"
                f"（平均いいね{wt['avg_like']} / {wt['count']}件）"
            )
        for s in low.get("worst_slots", []):
            st.markdown(
                f"- {s['day_name']}曜 {s['hour']}時台 は反応が低め"
                f"（平均{s['avg']} / {s['count']}件）"
            )
        st.caption("※ 件数が少ない時間帯は参考程度に")

# 🔍 競合から学ぶ
gap = summary.get("competitor_gap") or {}
if gap:
    st.markdown("##### 🔍 競合から学ぶ")
    gc1, gc2 = st.columns([1, 2])
    with gc1:
        my = gap.get("my_avg_like")
        comp = gap.get("competitor_avg_like")
        if my is not None and comp is not None:
            st.metric("平均いいね（妻 / 競合）", f"{my} / {comp}")
            st.caption(f"競合 {gap.get('competitor_count', 0)} アカウントとの比較")
    with gc2:
        tags = gap.get("unused_popular_tags", [])
        if tags:
            st.markdown("**競合がよく使うが未使用のタグ（試す価値あり）**")
            st.markdown("　".join(f"#{t['hashtag']}（{t['count']}回）" for t in tags))
        else:
            st.caption("未使用の人気タグは見つかりませんでした")
else:
    st.caption(
        "🔍 競合データを集めると「競合がよく使うが自分が未使用のタグ」も分かります"
        "（`python src/collect_competitors.py`）"
    )

st.markdown("##### 🤖 AIによる次の投稿アイデア")
st.caption("過去データと最新トレンドをもとに、Claudeが具体的な投稿案を作ります。")

gen_col, info_col = st.columns([1, 3])
with gen_col:
    do_generate = st.button("✨ 投稿案を作ってもらう", type="primary", use_container_width=True)
with info_col:
    regen = st.checkbox("最新で作り直す（再生成）", value=False)
    st.caption("※ 生成1回ごとにClaude API課金が発生します（同日はキャッシュ利用）")

if do_generate:
    from suggest import MissingAPIKeyError, generate_suggestions

    try:
        with st.spinner("Claudeが投稿案を考えています…（30秒ほど）"):
            st.session_state["suggestions"] = generate_suggestions(force=regen)
    except MissingAPIKeyError:
        st.error(
            "ANTHROPIC_API_KEY が設定されていません。`.env` に追加してから再度お試しください。"
        )
    except ImportError:
        st.error(
            "anthropic パッケージが未インストールです。"
            "`pip install -r requirements.txt` を実行してください。"
        )
    except Exception as e:  # noqa: BLE001 - ユーザーに原因を見せる
        st.error(f"生成中にエラーが発生しました: {e}")

result = st.session_state.get("suggestions")
if result:
    st.caption(f"生成日時: {result.get('generated_at', '—')}　|　モデル: {result.get('model', '—')}")
    suggestions = result.get("suggestions", [])
    for i, sug in enumerate(suggestions, 1):
        color = PRED_COLOR.get(sug.get("predicted_level", "中"), "#F56040")
        with st.container(border=True):
            head_l, head_r = st.columns([4, 1])
            with head_l:
                st.markdown(f"**案{i}: {sug.get('theme', '')}**")
            with head_r:
                st.markdown(
                    f"<span style='color:{color};font-weight:700'>"
                    f"予測 {sug.get('predicted_level', '—')}</span>",
                    unsafe_allow_html=True,
                )
            st.markdown(sug.get("caption_draft", ""))
            tags = sug.get("hashtags", []) or []
            if tags:
                st.caption("　".join(f"#{t.lstrip('#')}" for t in tags))
            st.caption(
                f"📸 {sug.get('media_type', '—')}　⏰ {sug.get('best_time', '—')}"
            )
            with st.expander("なぜ伸びそう？"):
                st.write(sug.get("rationale", ""))
