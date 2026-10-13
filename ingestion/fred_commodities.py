"""從 FRED 下載原物料價格與物價指數（月資料），輸出成一份 Parquet。

執行：python ingestion/fred_commodities.py
- 序列清單在 config/commodities.csv，新增原物料只改設定檔
- FRED 的歷史數字會被修正，所以每次都全部重抓（資料量很小，幾秒鐘）
- 某個序列下載失敗只會警告，不影響其他序列
"""
import io
import subprocess
import time
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path("config/commodities.csv")
RAW_DIR = Path("data/raw/fred")
PROCESSED_PATH = Path("data/processed/commodities/prices.parquet")
START = "2021-01-01"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch(series_id: str) -> str:
    cmd = ["curl", "-s", "-L", "--max-time", "60", 
           "-w", "\n%{http_code}", URL.format(series_id=series_id)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    body, _, status = result.stdout.rpartition("\n")
    if result.returncode != 0 or status != "200" or series_id not in body[:200]:
        raise ValueError(f"HTTP {status}，內容開頭：{body[:100]!r}")
    return body


def parse(csv_text: str, series_id: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = ["date", "value"]  # FRED 的日期欄名稱改過幾次，直接統一命名
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # 缺值在 FRED 是 "."
    df = df.dropna().sort_values("date")
    df["mom_pct"] = df["value"].pct_change() * 100
    df["yoy_pct"] = df["value"].pct_change(12) * 100
    df = df[df["date"] >= START]
    df["period"] = df["date"].dt.strftime("%Y-%m")
    df["series_id"] = series_id
    return df[["series_id", "period", "value", "mom_pct", "yoy_pct"]]


def main() -> None:
    config = pd.read_csv(CONFIG_PATH, dtype=str)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for row in config.itertuples():
        try:
            text = fetch(row.series_id)
        except ValueError as e:
            print(f"[警告] {row.series_id}（{row.name_zh}）下載失敗：{e}")
            continue
        (RAW_DIR / f"{row.series_id}.csv").write_text(text, encoding="utf-8")
        df = parse(text, row.series_id)
        frames.append(df)
        last = df.iloc[-1]
        print(f"{row.name_zh:<6} {len(df)} 個月，最新 {last.period}：{last.value:,.1f}（年增 {last.yoy_pct:+.1f}%）")
        time.sleep(1)

    if not frames:
        print("沒有任何資料")
        return
    out = pd.concat(frames, ignore_index=True)
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PROCESSED_PATH, index=False)
    print(f"\n共 {out['series_id'].nunique()} 個序列、{len(out)} 筆，已存：{PROCESSED_PATH}")


if __name__ == "__main__":
    main()
