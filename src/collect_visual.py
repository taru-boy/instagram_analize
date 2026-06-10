"""
Instagram 投稿画像の「軽量視覚特徴」収集スクリプト。

collect.py / collect_insights.py が見ていない「写真そのもの」を、
ローカルで（API課金なし）数値特徴に落とす。画家＝作品販売アカウントでは
色・明るさ・余白・描き込み量といった視覚特徴が保存率/リーチを左右するため、
これらを id ごとに抽出して CSV にキャッシュし、insights.py / dashboard.py で
エンゲージメントと相関させる。

- 画像は media_url（VIDEO は thumbnail_url）から **メモリに** ダウンロードするだけで、
  画像ファイルはローカル保存しない。抽出後の数値特徴のみ CSV に残す
  （毎回の再ダウンロード回避＋CDN URL 期限切れ後も分析を保持するため）。
- 既に特徴を持つ id はスキップ（増分実行）。--force で再計算。
- IG の CDN URL は期限切れで取得不能になるため、取れるうちに蓄積する。

抽出する特徴（計10）:
  色・明るさ系: brightness / saturation / contrast / colorfulness / warm_ratio / dominant_color
  構造・質感系: whitespace_ratio / edge_density / palette_size / sharpness

使い方:
    python src/collect_visual.py            # 直近 200 件のうち未処理を収集
    python src/collect_visual.py --limit 50 # 直近 50 件を対象
    python src/collect_visual.py --all      # 全件のうち未処理を収集
    python src/collect_visual.py --force    # 既に特徴がある id も再計算
"""

import argparse
import glob
import os
import time
from datetime import datetime as dt
from io import BytesIO

import numpy as np
import pandas as pd
import requests
from PIL import Image

from collect_utils import ensure_dir, load_env
from data_loader import load_media_data

# 特徴の列順（id をキーに、media_type / timestamp は参照用）
FEATURE_COLUMNS = [
    "brightness",
    "saturation",
    "contrast",
    "colorfulness",
    "warm_ratio",
    "dominant_color",
    "whitespace_ratio",
    "edge_density",
    "palette_size",
    "sharpness",
]
VISUAL_COLUMNS = ["id", "media_type", "timestamp"] + FEATURE_COLUMNS

# hue（0-360度）→ 色カテゴリ。dominant_color / palette_size で使用。
_HUE_BINS = [
    ("赤", lambda h: (h < 15) | (h >= 345)),
    ("橙", lambda h: (h >= 15) & (h < 45)),
    ("黄", lambda h: (h >= 45) & (h < 70)),
    ("緑", lambda h: (h >= 70) & (h < 170)),
    ("青", lambda h: (h >= 170) & (h < 260)),
    ("紫", lambda h: (h >= 260) & (h < 345)),
]


def _rgb_to_hsv(arr: np.ndarray):
    """0-1スケールの RGB 配列(HxWx3)を H(0-360)/S(0-1)/V(0-1) に変換（vectorized）。"""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    diff = mx - mn
    hue = np.zeros_like(mx)
    mask = diff > 1e-6
    rmask = mask & (mx == r)
    gmask = mask & (mx == g)
    bmask = mask & (mx == b)
    with np.errstate(invalid="ignore", divide="ignore"):
        hue[rmask] = (60 * ((g - b) / diff))[rmask] % 360
        hue[gmask] = (60 * ((b - r) / diff) + 120)[gmask]
        hue[bmask] = (60 * ((r - g) / diff) + 240)[bmask]
        sat = np.where(mx > 1e-6, diff / mx, 0.0)
    return hue, sat, mx


def extract_features(img: Image.Image) -> dict:
    """PIL Image から軽量視覚特徴を算出して dict で返す。"""
    img = img.convert("RGB")
    img.thumbnail((200, 200))  # 高速化のため縮小
    arr = np.asarray(img, dtype=np.float32) / 255.0
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
        return {}

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    hue, sat, val = _rgb_to_hsv(arr)

    # --- 色・明るさ系 ---
    brightness = float(lum.mean())
    contrast = float(lum.std())
    saturation = float(sat.mean())

    # colorfulness（Hasler–Süsstrunk, 0-255スケールで算出）
    r8, g8, b8 = r * 255, g * 255, b * 255
    rg = r8 - g8
    yb = 0.5 * (r8 + g8) - b8
    colorfulness = float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2)
        + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )

    # 彩度のある画素だけで色相を評価
    colored = sat > 0.15
    colored_total = int(colored.sum())
    warm = (hue <= 60) | (hue >= 300)
    warm_ratio = float(warm[colored].mean()) if colored_total > 0 else 0.0

    # dominant_color / palette_size
    dominant_color = "無彩色"
    palette_size = 0
    if colored_total > 0:
        hue_c = hue[colored]
        shares = {}
        for name, cond in _HUE_BINS:
            shares[name] = float(cond(hue_c).mean())
        dominant_color = max(shares, key=shares.get)
        # 全画素に対する有彩色割合が低ければ無彩色寄りとみなす
        if colored_total / hue.size < 0.10:
            dominant_color = "無彩色"
        palette_size = sum(1 for s in shares.values() if s >= 0.08)
    palette_size = max(palette_size, 1)

    # --- 構造・質感系 ---
    # 余白率: 明るく彩度の低い画素（紙・キャンバスの白地）の割合
    whitespace_ratio = float(((lum > 0.85) & (sat < 0.15)).mean())

    # 描き込み量: 隣接画素の輝度差（エッジ強度）の平均
    gx = np.abs(np.diff(lum, axis=1))
    gy = np.abs(np.diff(lum, axis=0))
    edge_density = float((gx.mean() + gy.mean()) / 2)

    # シャープさ: ラプラシアン分散（ピンボケほど小さい）
    lap = (
        4 * lum[1:-1, 1:-1]
        - lum[:-2, 1:-1]
        - lum[2:, 1:-1]
        - lum[1:-1, :-2]
        - lum[1:-1, 2:]
    )
    sharpness = float(lap.var()) if lap.size else 0.0

    return {
        "brightness": round(brightness, 4),
        "saturation": round(saturation, 4),
        "contrast": round(contrast, 4),
        "colorfulness": round(colorfulness, 2),
        "warm_ratio": round(warm_ratio, 4),
        "dominant_color": dominant_color,
        "whitespace_ratio": round(whitespace_ratio, 4),
        "edge_density": round(edge_density, 4),
        "palette_size": int(palette_size),
        "sharpness": round(sharpness, 4),
    }


def _existing_done_ids(out_dir: str) -> set:
    """過去の visual CSV で既に特徴を算出済み（brightness が非欠損）の id 集合。"""
    done = set()
    for f in glob.glob(os.path.join(out_dir, "*_visual_*.csv")):
        try:
            df = pd.read_csv(f)
        except Exception:
            continue
        if "id" not in df.columns or "brightness" not in df.columns:
            continue
        df["id"] = df["id"].astype(str)
        ok = df[df["brightness"].notna()]
        done.update(ok["id"].tolist())
    return done


def fetch_image(url: str, timeout: float = 15.0) -> Image.Image | None:
    """URL から画像をメモリに取得して PIL Image を返す。失敗時は None。"""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200 or not r.content:
            return None
        return Image.open(BytesIO(r.content))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Instagram 投稿画像の軽量視覚特徴を収集")
    parser.add_argument("--limit", type=int, default=200, help="対象にする直近メディア件数（デフォルト200）")
    parser.add_argument("--all", action="store_true", help="全メディアを対象にする")
    parser.add_argument("--sleep", type=float, default=0.2, help="ダウンロード間のウェイト秒")
    parser.add_argument("--force", action="store_true", help="既に特徴がある id も再計算する")
    args = parser.parse_args()

    result_dir = os.path.join(load_env().base_dir, "result")

    df_media = load_media_data(result_dir)
    if df_media.empty or "id" not in df_media.columns:
        print("メディアデータ（id 付き）が見つかりません。先に `python src/collect.py` を実行してください。")
        return

    # 直近順（CSVは新しい順）で対象を絞り、URL/id が有効な投稿だけ残す
    df_media = df_media.copy()
    df_media["id"] = df_media["id"].astype(str)
    target = df_media[
        df_media["id"].notna()
        & (df_media["id"].str.strip() != "")
        & df_media["media_url"].astype(str).str.startswith("http")
    ]
    if not args.all:
        target = target.head(args.limit)

    out_dir = os.path.join(result_dir, "visual")
    ensure_dir(out_dir)

    done_ids = set() if args.force else _existing_done_ids(out_dir)
    todo = target[~target["id"].isin(done_ids)]
    print(f"対象 {len(target)} 件 / 未処理 {len(todo)} 件（処理済み {len(target) - len(todo)} 件）")
    if todo.empty:
        print("新規に処理する画像はありません。--force で再計算できます。")
        return

    rows = []
    ok_count = 0
    for i, (_, post) in enumerate(todo.iterrows(), 1):
        img = fetch_image(str(post["media_url"]))
        feats = extract_features(img) if img is not None else {}
        row = {
            "id": post["id"],
            "media_type": post.get("media_type"),
            "timestamp": post.get("timestamp"),
        }
        row.update(feats)
        rows.append(row)
        if feats:
            ok_count += 1
        if i % 20 == 0:
            print(f"  {i}/{len(todo)} 件処理…（成功 {ok_count}）")
        time.sleep(args.sleep)

    df_out = pd.DataFrame(rows)
    for col in VISUAL_COLUMNS:
        if col not in df_out.columns:
            df_out[col] = None
    df_out = df_out[VISUAL_COLUMNS]

    today = dt.now().strftime("%Y-%m-%d")
    out_path = os.path.join(out_dir, f"{_target_label(result_dir)}_visual_{today}.csv")
    # 同日に複数回実行した場合は既存ぶんと結合して id 重複を除く
    if os.path.exists(out_path):
        try:
            prev = pd.read_csv(out_path)
            prev["id"] = prev["id"].astype(str)
            df_out = pd.concat([prev, df_out], ignore_index=True)
            df_out = df_out.drop_duplicates("id", keep="last")
        except Exception:
            pass
    df_out.to_csv(out_path, index=False)
    print(f"視覚特徴を保存: {out_path}（成功 {ok_count} / 取得失敗 {len(todo) - ok_count}）")
    print("視覚特徴の収集が完了しました。")


def _target_label(result_dir: str) -> str:
    """出力ファイル名に使うラベル（最新メディアCSVのユーザー名部分）。取れなければ visual。"""
    files = sorted(glob.glob(os.path.join(result_dir, "*.csv")))
    files = [f for f in files if "-profile-" not in os.path.basename(f)]
    if files:
        name = os.path.basename(files[-1])
        return name.rsplit("_", 1)[0]
    return "account"


if __name__ == "__main__":
    main()
