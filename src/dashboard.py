import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import (DAY_JA, load_media_data, load_profile_data,
                         merge_follower_at_post_date)

RESULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "result")

MEDIA_TYPE_JA = {"IMAGE": "画像", "CAROUSEL_ALBUM": "スライド", "VIDEO": "動画"}
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
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load_all_data():
    df_profile = load_profile_data(RESULT_DIR)
    df_media = load_media_data(RESULT_DIR)
    if not df_media.empty and not df_profile.empty:
        df_media = merge_follower_at_post_date(df_media, df_profile)
    return df_profile, df_media


df_profile, df_media = load_all_data()

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
c1, c2, c3, c4 = st.columns(4)

if not df_profile.empty:
    latest_followers = int(df_profile["followers_count"].iloc[-1])
    target = df_profile["date"].iloc[-1] - pd.Timedelta(days=30)
    past_df = df_profile[df_profile["date"] <= target]
    past_followers = int(past_df["followers_count"].iloc[-1]) if not past_df.empty else int(df_profile["followers_count"].iloc[0])
    delta = latest_followers - past_followers
    c1.metric("👥 フォロワー数", f"{latest_followers:,}", f"{delta:+,}（30日）")
else:
    c1.metric("👥 フォロワー数", "—")

if not df_f.empty and "engagement_rate" in df_f.columns:
    avg_eng = df_f["engagement_rate"].mean()
    c2.metric("💬 平均エンゲージメント率", f"{avg_eng:.2f}%")
    top_likes = int(df_f["like_count"].max())
    c3.metric("❤️ 最高いいね数", f"{top_likes:,}")
else:
    c2.metric("💬 平均エンゲージメント率", "—")
    c3.metric("❤️ 最高いいね数", "—")

c4.metric("📸 表示中の投稿数", f"{len(df_f):,}件")

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

if not df_f.empty:
    ctrl_l, ctrl_r = st.columns([3, 1])
    with ctrl_l:
        sort_options = {
            "like_count": "❤️ いいね数が多い順",
            "comments_count": "💬 コメント数が多い順",
            "engagement_rate": "📊 エンゲージメント率が高い順",
            "timestamp_jst": "🕐 新しい投稿順",
        }
        sort_col = st.selectbox(
            "並べ替え",
            options=list(sort_options.keys()),
            format_func=lambda x: sort_options[x],
        )
    with ctrl_r:
        n_show = st.select_slider("表示件数", options=[6, 9, 12, 18, 24, 30], value=12)

    df_sorted = df_f.sort_values(sort_col, ascending=False, na_position="last")
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

                eng_str = ""
                if "engagement_rate" in posts.columns and pd.notna(row.get("engagement_rate")):
                    eng_str = f"　📊 {row['engagement_rate']:.1f}%"
                st.caption(f"❤️ {int(row['like_count']):,}　💬 {int(row['comments_count']):,}{eng_str}")

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
            df_scatter["size_val"] = (df_scatter["like_count"] + 1).clip(upper=500)
            fig2 = px.scatter(
                df_scatter,
                x="timestamp_jst",
                y="engagement_rate",
                color="type_ja",
                size="size_val",
                size_max=25,
                hover_data={"like_count": True, "comments_count": True, "size_val": False, "type_ja": False},
                labels={
                    "timestamp_jst": "投稿日時",
                    "engagement_rate": "エンゲージメント率 (%)",
                    "type_ja": "タイプ",
                    "like_count": "いいね数",
                    "comments_count": "コメント数",
                },
                color_discrete_map={v: MEDIA_TYPE_COLOR[k] for k, v in MEDIA_TYPE_JA.items()},
            )
            fig2.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#f5f5f5"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig2, use_container_width=True)
            st.caption("円の大きさ = いいね数")
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
