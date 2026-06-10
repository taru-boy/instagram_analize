import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import (DAY_JA, add_saved_rate_adj,
                         load_account_insights_data, load_competitor_data,
                         load_hashtag_data, load_insights_data,
                         load_media_data, load_profile_data,
                         load_visual_data, merge_follower_at_post_date,
                         merge_insights, merge_visual)
from insights import (MEDIA_TYPE_JA, build_summary,
                      visual_engagement_analysis)

RESULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "result")

MEDIA_TYPE_COLOR = {"IMAGE": "#E1306C", "CAROUSEL_ALBUM": "#833AB4", "VIDEO": "#F56040"}

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
[data-testid="stSidebar"] { display: none; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load_all_data():
    df_profile = load_profile_data(RESULT_DIR)
    df_media = load_media_data(RESULT_DIR)
    if not df_media.empty and not df_profile.empty:
        df_media = merge_follower_at_post_date(df_media, df_profile)
    df_insights = load_insights_data(RESULT_DIR)
    if not df_media.empty:
        df_media = merge_insights(df_media, df_insights)
    df_visual = load_visual_data(RESULT_DIR)
    if not df_media.empty:
        df_media = merge_visual(df_media, df_visual)
    df_account_insights = load_account_insights_data(RESULT_DIR)
    df_competitors = load_competitor_data(RESULT_DIR)
    df_hashtags = load_hashtag_data(RESULT_DIR)
    return df_profile, df_media, df_competitors, df_hashtags, df_account_insights


df_profile, df_media, df_competitors, df_hashtags, df_account_insights = load_all_data()

HAS_INSIGHTS = (
    not df_media.empty
    and "reach" in df_media.columns
    and df_media["reach"].notna().any()
)

# -------- ページタイトル --------
st.title("🎨 Instagram 分析")
if not df_profile.empty:
    latest_date = df_profile["date"].iloc[-1].strftime("%Y年%m月%d日")
    st.caption(f"最終更新: {latest_date}　|　総投稿数: {len(df_media):,}件　|　同じWiFiのスマホからもアクセスできます 📱")

if df_profile.empty and df_media.empty:
    st.error("データが見つかりませんでした。result/ フォルダを確認してください。")
    st.stop()

# -------- KPI算出ヘルパー（タブ生成前に実行） --------

def _window_slice(df, anchor, days=30, offset=0):
    if df.empty or "post_date" not in df.columns:
        return df.iloc[0:0]
    end = anchor - pd.Timedelta(days=offset)
    start = anchor - pd.Timedelta(days=offset + days)
    return df[(df["post_date"] > start) & (df["post_date"] <= end)]


def _window_rate(df, num_col, den_col="reach"):
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
    if df.empty or col not in df.columns:
        return None, 0
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return None, 0
    return float(s.mean()), int(len(s))


def _fmt_delta(recent, prev, kind):
    if recent is None or prev is None:
        return None
    d = recent - prev
    if kind == "pt":
        return f"{d:+.1f}pt"
    if kind == "int":
        return f"{d:+,.0f}"
    return f"{d:+,.1f}"


def _followers_at(df_profile, when):
    sub = df_profile[df_profile["date"] <= when]
    return int(sub["followers_count"].iloc[-1]) if not sub.empty else None


def _val(x, fmt):
    return "—" if x is None else fmt(x)


# 「質の比較」用の期間プリセット。昔（〜2023）は保存率の地合いが今の約60倍あり、
# 全期間で比べると古い投稿が上位を独占して「今効く型」が見えなくなるため、
# 投稿一覧・写真の傾向分析は期間を絞って比較する（既定: 直近12ヶ月）。
PERIOD_OPTIONS = {3: "直近3ヶ月", 6: "直近6ヶ月", 12: "直近12ヶ月", 24: "直近24ヶ月", None: "全期間"}


def _period_window(df, months):
    """timestamp_jst が直近 months ヶ月以内の行に絞る。months=None なら全期間。"""
    if months is None or df.empty or "timestamp_jst" not in df.columns:
        return df
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
    return df[df["timestamp_jst"] >= cutoff]


def _select_period(key: str, label: str = "対象期間", help_text: str | None = None):
    """PERIOD_OPTIONS に基づく期間セレクタ。既定は直近12ヶ月。"""
    return st.selectbox(
        label,
        options=list(PERIOD_OPTIONS.keys()),
        format_func=lambda x: PERIOD_OPTIONS[x],
        index=2,
        key=key,
        help=help_text,
    )


def _kpi(col, label: str, value, fmt, *, recent=None, prev=None, delta_kind=None, help_text: str | None = None):
    """1つの KPI カードを描画する。"""
    col.metric(
        label,
        _val(value, fmt),
        delta=_fmt_delta(recent, prev, delta_kind) if delta_kind else None,
        help=help_text,
    )


def _account_nf_rate(df_ai, anchor, days=30, offset=0):
    """アカウント日次インサイトから直近days日のフォロワー外リーチ比率を返す。
    メディア単位の breakdown は Instagram API v22.0 で非対応になったため
    アカウント集計（df_account_insights）から算出する。"""
    if df_ai.empty or "reach_non_follower" not in df_ai.columns:
        return None
    end = anchor - pd.Timedelta(days=offset)
    start = anchor - pd.Timedelta(days=offset + days)
    w = df_ai[(df_ai["date"] > start) & (df_ai["date"] <= end)]
    nf = pd.to_numeric(w["reach_non_follower"], errors="coerce")
    r = pd.to_numeric(w["reach"], errors="coerce")
    mask = r.notna() & (r > 0) & nf.notna()
    if mask.sum() == 0:
        return None
    return float(nf[mask].sum() / r[mask].sum() * 100)


_now = pd.Timestamp.now().normalize()
win_recent = _window_slice(df_media, _now, days=30, offset=0)
win_prev = _window_slice(df_media, _now, days=30, offset=30)

sr_now, n_recent = _window_rate(win_recent, "saved", "reach")
sr_prev, _ = _window_rate(win_prev, "saved", "reach")
reach_now, _ = _window_mean(win_recent, "reach")
reach_prev, _ = _window_mean(win_prev, "reach")
pv_now, _ = _window_mean(win_recent, "profile_visits")
pv_prev, _ = _window_mean(win_prev, "profile_visits")
nf_now = _account_nf_rate(df_account_insights, _now, days=30, offset=0)
nf_prev = _account_nf_rate(df_account_insights, _now, days=30, offset=30)
eng_now, _ = _window_engagement_rate(win_recent)
eng_prev, _ = _window_engagement_rate(win_prev)
sh_now, _ = _window_mean(win_recent, "shares")
sh_prev, _ = _window_mean(win_prev, "shares")
n_prev = len(win_prev)

latest_followers = None
gain_now = None
gain_prev = None
if not df_profile.empty:
    latest_followers = int(df_profile["followers_count"].iloc[-1])
    p_now = df_profile["date"].iloc[-1]
    f_now = latest_followers
    f_30 = _followers_at(df_profile, p_now - pd.Timedelta(days=30))
    f_60 = _followers_at(df_profile, p_now - pd.Timedelta(days=60))
    if f_30 is None:
        f_30 = int(df_profile["followers_count"].iloc[0])
    gain_now = f_now - f_30
    if f_60 is not None:
        gain_prev = f_30 - f_60

# 投稿提案サマリ（全タブ共通、全期間データ）
summary = build_summary(df_media, df_competitors, df_hashtags)
PRED_COLOR = {"高": "#E1306C", "中": "#F56040", "低": "#9e9e9e"}

# -------- 4タブ --------
tab_home, tab_trend, tab_detail, tab_idea = st.tabs(
    ["🏠 ホーム", "📈 トレンド", "📊 詳しい分析", "💡 投稿アイデア"]
)

# ========================================
# タブ1: ホーム
# ========================================
with tab_home:
    # === 重視KPI（直近30日固定） ===
    st.markdown("##### 🎯 直近30日の重視KPI（前30日比）　— 発見 → 保存 → プロフィール訪問 → フォロー")
    k1, k2, k3, k4 = st.columns(4)

    _kpi(k1, "🔖 保存率", sr_now, lambda v: f"{v:.2f}%",
         recent=sr_now, prev=sr_prev, delta_kind="pt",
         help_text="保存数の合計 ÷ リーチの合計（リーチ加重）。作品が刺さった最良のシグナル。1%超で優秀。"
                   if HAS_INSIGHTS else "`python src/collect_insights.py` でインサイトを収集すると表示されます")
    _kpi(k2, "👀 平均リーチ", reach_now, lambda v: f"{v:,.0f}",
         recent=reach_now, prev=reach_prev, delta_kind="int",
         help_text="1投稿が届いた人数の平均。リール・保存・シェアで新規の発見が増えます。")
    _kpi(k3, "🏠 平均プロフィール訪問", pv_now, lambda v: f"{v:,.1f}",
         recent=pv_now, prev=pv_prev, delta_kind="float1",
         help_text="投稿を見てプロフィールに来た数（投稿あたり平均）。販売・受注の入口。")
    _kpi(k4, "📈 フォロワー純増", gain_now, lambda v: f"{v:+,}",
         recent=gain_now, prev=gain_prev, delta_kind="int",
         help_text="直近30日のフォロワー純増。デルタは前30日の純増との差。")

    # === 補助KPI ===
    s1, s2, s3, s4 = st.columns(4)
    _kpi(s1, "🆕 フォロワー外リーチ比率", nf_now, lambda v: f"{v:.0f}%",
         recent=nf_now, prev=nf_prev, delta_kind="pt",
         help_text="フォロワー以外に届いたリーチの割合（リーチ加重）。リールで伸ばせます。")
    _kpi(s2, "👥 フォロワー数", latest_followers, lambda v: f"{v:,}")
    _kpi(s3, "💬 エンゲージ率（リーチ基準）", eng_now, lambda v: f"{v:.2f}%",
         recent=eng_now, prev=eng_prev, delta_kind="pt",
         help_text="(いいね＋コメント) の合計 ÷ リーチの合計。")
    _kpi(s4, "🔁 平均シェア数", sh_now, lambda v: f"{v:,.1f}",
         recent=sh_now, prev=sh_prev, delta_kind="float1",
         help_text="ストーリーズ/DMでの共有（投稿あたり平均）。")

    st.caption(
        f"※ 上段KPIは**直近30日**の投稿 {n_recent} 件（前30日は {n_prev} 件）から算出・前30日比。"
        "比率はリーチ加重。フォロワー純増は最新−30日前。"
    )
    if not df_account_insights.empty:
        last = df_account_insights.iloc[-1]
        st.caption(
            f"🔗 直近のアカウント全体: プロフィールアクセス {int(last['profile_views']):,} ／ "
            f"リンククリック {int(last['website_clicks'])} 回（{last['date'].strftime('%m月%d日')}時点）"
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

    # === 投稿パフォーマンス一覧 ===
    st.subheader("🏆 投稿パフォーマンス一覧")
    st.caption(
        "📊＝総エンゲージ率（いいね＋コメント＋**保存＋シェア** ÷ 投稿時点フォロワー）。"
        "保存・シェアはインサイトのある投稿でのみ加算されます。"
    )

    if not df_media.empty:
        ctrl_l, ctrl_m, ctrl_r = st.columns([2, 1, 1])
        with ctrl_l:
            if HAS_INSIGHTS:
                sort_options = {
                    "saved_rate_adj": "🔖 保存率（調整済み・低リーチ補正）が高い順",
                    "saved": "🔖 保存数が多い順",
                    "reach": "👀 リーチが多い順",
                    "shares": "🔁 シェア数が多い順",
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
            sort_options = {k: v for k, v in sort_options.items() if k in df_media.columns}
            sort_col = st.selectbox(
                "並べ替え",
                options=list(sort_options.keys()),
                format_func=lambda x: sort_options[x],
            )
        with ctrl_m:
            period_months = _select_period(
                "period_home",
                help_text="昔（〜2023年）は保存率の地合いが今の約60倍。全期間だと古い投稿が上位を独占するため、"
                          "「今効く型」を見るには期間を絞って比較します。",
            )
        with ctrl_r:
            n_show = st.select_slider("表示件数", options=[6, 9, 12, 18, 24, 30], value=12)

        # 期間で絞り、その期間の地合い（m・C）で調整保存率を再計算する
        df_list = _period_window(df_media, period_months)
        if HAS_INSIGHTS:
            df_list = add_saved_rate_adj(df_list)

        if sort_col == "saved_rate_adj":
            st.caption(
                f"調整保存率＝(保存+m×C)/(リーチ+C)。リーチが小さい投稿の保存率を**{PERIOD_OPTIONS[period_months]}の平均**へ"
                "補正し、まぐれの高保存率に上位を占有されないようにしています（m・Cはこの期間で再計算）。"
            )

        df_sorted = df_list.sort_values(sort_col, ascending=False, na_position="last")
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

                    eng_val = row.get("total_engagement_rate")
                    if pd.isna(eng_val):
                        eng_val = row.get("engagement_rate")
                    eng_str = f"　📊 {eng_val:.1f}%" if pd.notna(eng_val) else ""
                    st.caption(f"❤️ {int(row['like_count']):,}　💬 {int(row['comments_count']):,}{eng_str}")

                    if HAS_INSIGHTS and pd.notna(row.get("reach")):
                        ins_parts = [f"👀 {int(row['reach']):,}", f"🔖 {int(row['saved'])}", f"🔁 {int(row['shares'])}"]
                        if pd.notna(row.get("views")):
                            ins_parts.append(f"▶️ {int(row['views']):,}")
                        st.caption("　".join(ins_parts))

        st.caption("※ Instagram のCDN画像は有効期限があります。古い投稿は表示されない場合があります。")
    else:
        st.info("投稿データがまだありません")

# ========================================
# タブ2: トレンド（継続・成長の見える化）
# ========================================
with tab_trend:
    st.subheader("📈 トレンド　— 継続・成長の見える化（全期間）")

    # --- フォロワー数推移 ---
    st.markdown("##### 👥 フォロワー数推移")
    if not df_profile.empty:
        fig_fw = px.line(
            df_profile,
            x="date",
            y="followers_count",
            labels={"date": "日付", "followers_count": "フォロワー数"},
            markers=True,
        )
        fig_fw.update_traces(line_color="#E1306C", marker_color="#E1306C", marker_size=5)
        fig_fw.update_layout(
            plot_bgcolor="white",
            hovermode="x unified",
            yaxis=dict(gridcolor="#f5f5f5"),
            xaxis=dict(gridcolor="#f5f5f5"),
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_fw, use_container_width=True)
    else:
        st.info("プロフィールデータがまだありません（`python src/collect.py` を実行してください）")

    st.divider()

    # --- 累積投稿数推移 ---
    st.markdown("##### 📝 累積投稿数の推移")
    if not df_media.empty:
        df_cum = (
            df_media[["post_date"]].dropna()
            .sort_values("post_date")
            .copy()
        )
        df_cum["累積投稿数"] = range(1, len(df_cum) + 1)
        fig_cum = px.line(
            df_cum,
            x="post_date",
            y="累積投稿数",
            labels={"post_date": "投稿日"},
        )
        fig_cum.update_traces(line_color="#833AB4", line_width=2)
        fig_cum.update_layout(
            plot_bgcolor="white",
            hovermode="x unified",
            yaxis=dict(gridcolor="#f5f5f5"),
            xaxis=dict(gridcolor="#f5f5f5"),
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_cum, use_container_width=True)
        st.caption(f"現在の累積投稿数: {len(df_media):,} 件")
    else:
        st.info("投稿データがまだありません")

    st.divider()

    # --- 月次の平均リーチ・平均保存数 ---
    st.markdown("##### 📊 月次の平均リーチ・平均保存数の推移")
    if HAS_INSIGHTS:
        df_ins_monthly = df_media[df_media["reach"].notna()].copy()
        if not df_ins_monthly.empty:
            df_ins_monthly["month"] = df_ins_monthly["post_date"].dt.to_period("M").dt.to_timestamp()
            monthly = (
                df_ins_monthly.groupby("month")
                .agg(平均リーチ=("reach", "mean"), 平均保存数=("saved", "mean"))
                .reset_index()
            )
            monthly["平均リーチ"] = monthly["平均リーチ"].round(0)
            monthly["平均保存数"] = monthly["平均保存数"].round(1)

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                fig_mr = px.line(
                    monthly, x="month", y="平均リーチ",
                    labels={"month": "月", "平均リーチ": "平均リーチ数"},
                    markers=True,
                )
                fig_mr.update_traces(line_color="#E1306C", marker_color="#E1306C", marker_size=6)
                fig_mr.update_layout(
                    plot_bgcolor="white", hovermode="x unified",
                    yaxis=dict(gridcolor="#f5f5f5"), xaxis=dict(gridcolor="#f5f5f5"),
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig_mr, use_container_width=True)
            with col_m2:
                fig_ms = px.line(
                    monthly, x="month", y="平均保存数",
                    labels={"month": "月", "平均保存数": "平均保存数"},
                    markers=True,
                )
                fig_ms.update_traces(line_color="#F56040", marker_color="#F56040", marker_size=6)
                fig_ms.update_layout(
                    plot_bgcolor="white", hovermode="x unified",
                    yaxis=dict(gridcolor="#f5f5f5"), xaxis=dict(gridcolor="#f5f5f5"),
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig_ms, use_container_width=True)
        else:
            st.info("インサイト付きの投稿データがありません")
    else:
        st.info(
            "💡 `python src/collect_insights.py` でインサイトを収集すると、"
            "月次の平均リーチ・保存数の推移が表示されます。"
        )

    st.divider()

    # --- アカウント日次インサイト推移 ---
    st.markdown("##### 🔗 アカウント日次インサイトの推移")
    if not df_account_insights.empty:
        ai_cols = [c for c in ["profile_views", "reach", "website_clicks"] if c in df_account_insights.columns]
        if ai_cols:
            df_ai_sorted = df_account_insights.sort_values("date")
            label_map = {"profile_views": "プロフィールアクセス", "reach": "リーチ", "website_clicks": "リンククリック"}
            col_names = {c: label_map.get(c, c) for c in ai_cols}
            df_ai_plot = df_ai_sorted[["date"] + ai_cols].rename(columns=col_names)

            fig_ai = px.line(
                df_ai_plot.melt(id_vars="date", var_name="指標", value_name="値"),
                x="date",
                y="値",
                color="指標",
                labels={"date": "日付", "値": "件数"},
                markers=True,
            )
            fig_ai.update_layout(
                plot_bgcolor="white",
                hovermode="x unified",
                yaxis=dict(gridcolor="#f5f5f5"),
                xaxis=dict(gridcolor="#f5f5f5"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig_ai, use_container_width=True)
            st.caption("日次cronで毎日 `run.sh` を実行すると蓄積されていきます。")
        else:
            st.info("日次インサイト列が見つかりません")
    else:
        st.info(
            "💡 `python src/collect_insights.py` を日次で実行するとアカウント全体の"
            "プロフィールアクセス・リーチ・リンククリックの推移が表示されます（`run.sh` 参照）。"
        )

# ========================================
# タブ3: 詳しい分析（保存/リーチ軸）
# ========================================
with tab_detail:
    st.subheader("📊 詳しい分析")
    st.caption(
        "インサイト取得済みの投稿のみが対象です（写真の傾向タブは視覚特徴がある投稿が対象）。"
    )

    df_ri = df_media[df_media["reach"].notna()].copy() if HAS_INSIGHTS and "reach" in df_media.columns else pd.DataFrame()

    d_tab1, d_tab2, d_tab3, d_tab4, d_tab5 = st.tabs(
        ["📌 タイプ別の効き目", "🗓️ 投稿タイミング", "📈 リーチ・発見の推移", "🔖 ハッシュタグ", "🎨 写真の傾向"]
    )

    # --- タイプ別の効き目 ---
    with d_tab1:
        st.markdown("**投稿タイプ別の平均指標**　— 「どの型が販売導線に効くか」")
        if not df_ri.empty:
            agg_dict = {"reach": "mean", "saved": "mean", "like_count": "count"}
            if "profile_visits" in df_ri.columns:
                agg_dict["profile_visits"] = "mean"
            type_ins = df_ri.groupby("media_type").agg(**{
                "平均リーチ": ("reach", "mean"),
                "平均保存数": ("saved", "mean"),
                "投稿数": ("reach", "count"),
            }).reset_index()
            if "profile_visits" in df_ri.columns and df_ri["profile_visits"].notna().any():
                pv_by_type = df_ri.groupby("media_type")["profile_visits"].mean().reset_index()
                pv_by_type.columns = ["media_type", "平均プロフィール訪問"]
                type_ins = type_ins.merge(pv_by_type, on="media_type", how="left")
            type_ins["タイプ"] = type_ins["media_type"].map(MEDIA_TYPE_JA).fillna(type_ins["media_type"])
            type_ins["平均リーチ"] = type_ins["平均リーチ"].round(0)
            type_ins["平均保存数"] = type_ins["平均保存数"].round(1)

            plot_cols = ["平均リーチ", "平均保存数"]
            if "平均プロフィール訪問" in type_ins.columns:
                type_ins["平均プロフィール訪問"] = type_ins["平均プロフィール訪問"].round(1)
                plot_cols.append("平均プロフィール訪問")

            n_plots = len(plot_cols)
            cols_type = st.columns(n_plots)
            for ci, metric in enumerate(plot_cols):
                with cols_type[ci]:
                    fig_t = px.bar(
                        type_ins, x="タイプ", y=metric, text=metric,
                        color="タイプ",
                        color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()),
                        title=f"タイプ別 {metric}",
                    )
                    fmt = ":.0f" if "リーチ" in metric else ":.1f"
                    fig_t.update_traces(texttemplate=f"%{{text{fmt}}}", textposition="outside")
                    fig_t.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_t, use_container_width=True)

            st.dataframe(
                type_ins.drop(columns=["media_type"]).set_index("タイプ"),
                use_container_width=True,
            )
        elif not df_media.empty:
            # インサイト未取得時：いいね基準フォールバック
            st.info("💡 インサイト未取得のため、いいね数基準で表示しています。")
            type_stats = (
                df_media.groupby("media_type")
                .agg(平均いいね数=("like_count", "mean"), 投稿数=("like_count", "count"))
                .reset_index()
            )
            type_stats["タイプ"] = type_stats["media_type"].map(MEDIA_TYPE_JA).fillna(type_stats["media_type"])
            fig_fb = px.bar(
                type_stats, x="タイプ", y="平均いいね数", text="平均いいね数", color="タイプ",
                color_discrete_sequence=list(MEDIA_TYPE_COLOR.values()),
            )
            fig_fb.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            fig_fb.update_layout(plot_bgcolor="white", showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_fb, use_container_width=True)
        else:
            st.info("データがありません")

    # --- 投稿タイミング ---
    with d_tab2:
        if HAS_INSIGHTS and not df_ri.empty and "saved" in df_ri.columns and df_ri["saved"].notna().any():
            st.markdown("**曜日・時間帯別の平均保存数**（どの時間帯に保存されやすいか）")
            pivot_val = "saved"
            pivot_label = "平均保存数"
        else:
            st.markdown("**曜日・時間帯別の平均いいね数**（投稿が多い時間帯を知る）")
            pivot_val = "like_count"
            pivot_label = "平均いいね数"
            if not HAS_INSIGHTS:
                st.caption("💡 インサイト取得後は保存数基準のヒートマップに切り替わります。")

        df_pivot_src = df_ri if (HAS_INSIGHTS and not df_ri.empty) else df_media
        if not df_pivot_src.empty and "day_name" in df_pivot_src.columns:
            pivot = df_pivot_src.pivot_table(
                values=pivot_val, index="day_name", columns="hour", aggfunc="mean"
            )
            pivot = pivot.reindex([d for d in DAY_JA if d in pivot.index])
            pivot.columns = [f"{h}時" for h in pivot.columns]
            fig_heat = px.imshow(
                pivot,
                labels={"x": "時間帯 (JST)", "y": "曜日", "color": pivot_label},
                color_continuous_scale="RdPu",
                aspect="auto",
            )
            fig_heat.update_layout(margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_heat, use_container_width=True)
            st.caption("※ 投稿数が少ない時間帯は参考程度にご覧ください")
        else:
            st.info("データがありません")

    # --- リーチ・発見の推移 ---
    with d_tab3:
        if not df_ri.empty:
            df_ri_sorted = df_ri.sort_values("timestamp_jst")
            df_ri_sorted["type_ja"] = df_ri_sorted["media_type"].map(MEDIA_TYPE_JA).fillna(df_ri_sorted["media_type"])

            st.markdown("**リーチ推移**")
            fig_r = px.bar(
                df_ri_sorted, x="timestamp_jst", y="reach",
                color="type_ja",
                labels={"timestamp_jst": "投稿日時", "reach": "リーチ数", "type_ja": "タイプ"},
                color_discrete_map={v: MEDIA_TYPE_COLOR[k] for k, v in MEDIA_TYPE_JA.items()},
            )
            fig_r.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#f5f5f5"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_r, use_container_width=True)

            has_nf = "non_follower_reach_rate" in df_ri.columns and df_ri["non_follower_reach_rate"].notna().any()
            if has_nf:
                st.markdown("**フォロワー外リーチ比率の推移**　— 新規（フォロワー以外）にどれだけ届いたか")
                df_nf = df_ri[df_ri["non_follower_reach_rate"].notna()].sort_values("timestamp_jst").copy()
                df_nf["type_ja"] = df_nf["media_type"].map(MEDIA_TYPE_JA).fillna(df_nf["media_type"])
                fig_nf = px.bar(
                    df_nf, x="timestamp_jst", y="non_follower_reach_rate",
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
                st.caption(f"平均フォロワー外リーチ比率: {avg_nf:.1f}%")
        else:
            st.info(
                "💡 `python src/collect_insights.py` でインサイトを収集すると"
                "リーチ・発見の推移が表示されます。"
            )

    # --- ハッシュタグ ---
    with d_tab4:
        if not df_media.empty and "hashtag" in df_media.columns:
            hashtag_rows = []
            for _, row in df_media.iterrows():
                if pd.isna(row["hashtag"]) or str(row["hashtag"]).strip() == "":
                    continue
                for tag in str(row["hashtag"]).split("\n"):
                    tag = tag.strip()
                    if tag:
                        base = {"hashtag": f"#{tag}"}
                        if HAS_INSIGHTS and pd.notna(row.get("reach")):
                            base["reach"] = row["reach"]
                        if HAS_INSIGHTS and pd.notna(row.get("saved")):
                            base["saved"] = row.get("saved", 0)
                        base["like_count"] = row["like_count"]
                        hashtag_rows.append(base)

            if hashtag_rows:
                df_tags = pd.DataFrame(hashtag_rows)

                if HAS_INSIGHTS and "saved" in df_tags.columns:
                    tab_h1_label = "🔖 保存数が多いタグ TOP20"
                    rank_col = "saved"
                    rank_label = "平均保存数"
                else:
                    tab_h1_label = "❤️ いいねが多いタグ TOP20"
                    rank_col = "like_count"
                    rank_label = "平均いいね数"

                tab_h1, tab_h2 = st.tabs([tab_h1_label, "📊 よく使うタグ TOP20"])

                with tab_h1:
                    top_rank = (
                        df_tags.groupby("hashtag")[rank_col]
                        .mean()
                        .reset_index()
                        .sort_values(rank_col, ascending=False)
                        .head(20)
                    )
                    top_rank.columns = ["ハッシュタグ", rank_label]
                    top_rank[rank_label] = top_rank[rank_label].round(1)
                    fig_h1 = px.bar(
                        top_rank.iloc[::-1],
                        x=rank_label,
                        y="ハッシュタグ",
                        orientation="h",
                        color=rank_label,
                        color_continuous_scale="RdPu",
                    )
                    fig_h1.update_layout(
                        plot_bgcolor="white", coloraxis_showscale=False,
                        height=520, margin=dict(l=0, r=0, t=10, b=0),
                    )
                    st.plotly_chart(fig_h1, use_container_width=True)

                with tab_h2:
                    freq = df_tags["hashtag"].value_counts().reset_index().head(20)
                    freq.columns = ["ハッシュタグ", "使用回数"]
                    fig_h2 = px.bar(
                        freq.iloc[::-1],
                        x="使用回数",
                        y="ハッシュタグ",
                        orientation="h",
                        color="使用回数",
                        color_continuous_scale="PuRd",
                    )
                    fig_h2.update_layout(
                        plot_bgcolor="white", coloraxis_showscale=False,
                        height=520, margin=dict(l=0, r=0, t=10, b=0),
                    )
                    st.plotly_chart(fig_h2, use_container_width=True)
            else:
                st.info("ハッシュタグデータがありません")
        else:
            st.info("投稿データがありません")

    # --- 写真の傾向（視覚特徴 × エンゲージ） ---
    with d_tab5:
        period_v = _select_period(
            "visual_period",
            help_text="保存率の地合いは年々大きく下がっているため、昔と今を混ぜると傾向がぼやけます。"
                      "「今効く見た目」を見るには直近に絞ってください。",
        )
        df_vis = _period_window(df_media, period_v)
        df_vis = add_saved_rate_adj(df_vis)  # その期間の地合いで再正規化
        va = visual_engagement_analysis(df_vis)
        if va and (va.get("features") or va.get("dominant_color")):
            metric_label = va.get("metric_label", "エンゲージ")
            st.markdown(
                f"**写真の見え方 × {metric_label}**　— どんな絵が刺さるか"
                f"（{PERIOD_OPTIONS[period_v]}・{va.get('n', 0)}件の投稿が対象）"
            )
            st.caption(
                "各特徴を投稿を5分位（最低/低/中/高/最高）に分け、帯ごとの平均を比較しています。"
                "色みや明るさを機械的に測ったもので、モチーフ（何が描かれているか）は対象外です。"
            )

            BAND_ORDER = ["最低", "低", "中", "高", "最高"]
            feats = va.get("features", {})
            feat_keys = list(feats.keys())
            for i in range(0, len(feat_keys), 3):
                cols_v = st.columns(3)
                for j in range(3):
                    if i + j >= len(feat_keys):
                        break
                    key = feat_keys[i + j]
                    info = feats[key]
                    dfb = pd.DataFrame(info["ranking"])
                    dfb["band"] = pd.Categorical(dfb["band"], categories=BAND_ORDER, ordered=True)
                    dfb = dfb.sort_values("band")
                    with cols_v[j]:
                        fig_v = px.bar(
                            dfb, x="band", y="avg", text="avg",
                            labels={"band": info["label"], "avg": f"平均{metric_label}"},
                            title=info["label"],
                            color="band",
                            color_discrete_sequence=["#c5cae9", "#9fa8da", "#7986cb", "#5c6bc0", "#E1306C"],
                        )
                        fig_v.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                        fig_v.update_layout(
                            plot_bgcolor="white", showlegend=False,
                            margin=dict(l=0, r=0, t=40, b=0), height=260,
                        )
                        st.plotly_chart(fig_v, use_container_width=True)

            dc = va.get("dominant_color") or {}
            if dc.get("ranking"):
                st.markdown(f"**主要色（画面で一番面積を占める色相）× 平均{metric_label}**")
                dfc = pd.DataFrame(dc["ranking"])
                fig_c = px.bar(
                    dfc, x="color", y="avg", text="avg",
                    labels={"color": "主要色", "avg": f"平均{metric_label}"},
                    color="avg", color_continuous_scale="RdPu",
                )
                fig_c.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                fig_c.update_layout(
                    plot_bgcolor="white", coloraxis_showscale=False,
                    margin=dict(l=0, r=0, t=10, b=0), height=320,
                )
                st.plotly_chart(fig_c, use_container_width=True)
            st.caption(
                "※ 件数が少ない帯は参考程度に。IGの表示画像（中央クロップされることあり）を基準にしています。"
            )
        elif "brightness" in df_media.columns and df_media["brightness"].notna().any():
            st.info(
                f"この期間（{PERIOD_OPTIONS[period_v]}）は分析に十分な投稿がありません。"
                "対象期間を広げてください（5分位の集計には10件程度必要です）。"
            )
        else:
            st.info(
                "💡 `python src/collect_visual.py` を実行すると、写真の色み・明るさ・余白などを"
                "数値化し、どんな見た目の作品が伸びるかを分析できます（API課金なし）。"
            )

# ========================================
# タブ4: 投稿アイデア
# ========================================
with tab_idea:
    st.subheader("💡 投稿アイデア")

    # --- 次にやるべきこと（先頭3件 + もっと見る）---
    st.markdown("##### 📋 次にやるべきこと")
    advice = summary.get("advice", [])
    if advice:
        with st.container(border=True):
            for a in advice[:3]:
                st.markdown(f"- {a}")
        if len(advice) > 3:
            with st.expander(f"もっと見る（残り {len(advice) - 3} 件）"):
                for a in advice[3:]:
                    st.markdown(f"- {a}")
        st.caption("※ 過去データの数値根拠にもとづく提案です（AI不使用・無料）")
    else:
        st.info("データが貯まるとここに具体的な提案が表示されます")

    st.divider()

    # --- 伸びる条件 ---
    with st.expander("📌 データから見た「伸びる条件」"):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            if summary["best_slots"]:
                s = summary["best_slots"][0]
                st.metric("⏰ 反応が良い投稿タイミング", f"{s['day_name']}曜 {s['hour']}時台")
                others = "　".join(f"{x['day_name']}曜{x['hour']}時" for x in summary["best_slots"][1:3])
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
            trend_tags = "　".join(f"#{t['hashtag']}" for t in summary["trending_topics"][:10])
            st.markdown(f"**🌐 業界トレンド（競合・人気タグ投稿で多用）**\n\n{trend_tags}")
        else:
            st.caption(
                "💡 競合・ハッシュタグのトレンドデータを集めると、より精度の高い提案ができます"
                "（`python src/collect_competitors.py` / `python src/collect_hashtags.py`）"
            )

    # --- 伸びる投稿の型 ---
    with st.expander("📐 伸びる投稿の「型」（キャプション長・タグ数・投稿ペース）"):
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
                trend_str = cad.get("trend", "")
                prev_cad = cad.get("older_per_week")
                st.caption(f"傾向: {trend_str}" + (f"（以前は週{prev_cad}件）" if prev_cad else ""))
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

    # --- 避けたい条件 ---
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

    st.divider()

    # --- AI投稿案（最下部・折りたたみ） ---
    with st.expander("🤖 AIで投稿案を作る（任意・課金あり）", expanded=False):
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
                st.error("ANTHROPIC_API_KEY が設定されていません。`.env` に追加してから再度お試しください。")
            except ImportError:
                st.error("anthropic パッケージが未インストールです。`pip install -r requirements.txt` を実行してください。")
            except Exception as e:  # noqa: BLE001
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
                    st.caption(f"📸 {sug.get('media_type', '—')}　⏰ {sug.get('best_time', '—')}")
                    with st.expander("なぜ伸びそう？"):
                        st.write(sug.get("rationale", ""))
