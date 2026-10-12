"""抓取證交所上市公司「最新一個月」營收，篩選追蹤清單，存成 raw JSON 與 Parquet。

執行：python ingestion/twse_revenue.py
資料單位：新台幣千元
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

API_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"

# 第一階段：中游製造 + AI 伺服器（皆為上市公司；上櫃公司之後用櫃買中心 API 補）
WATCHLIST = {
    "2330": "台積電",
    "3711": "日月光投控",
    "2408": "南亞科",
    "3037": "欣興",
    "8046": "南電",
    "3189": "景碩",
    "2368": "金像電",
    "2383": "台光電",
    "2317": "鴻海",
    "2382": "廣達",
    "3231": "緯創",
    "6669": "緯穎",
    "2308": "台達電",
    "3017": "奇鋐",
}

RAW_DIR = Path("data/raw/twse_monthly_revenue")
PROCESSED_DIR = Path("data/processed/twse_monthly_revenue")


def fetch_raw() -> list[dict]:
    resp = requests.get(API_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_raw(records: list[dict], run_date: str) -> Path:
    """原始資料原封不動保存，之後轉換出錯可以重跑，不用再打 API。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{run_date}.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def roc_to_period(roc: str) -> str:
    """民國年月轉西元，例如 '11509' -> '2026-09'。"""
    roc = str(roc).strip()
    return f"{int(roc[:-2]) + 1911}-{roc[-2:]}"


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def transform(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    # 欄位名稱有時用 '-' 有時用 '_'，統一成 '_'
    df.columns = [c.replace("-", "_").strip() for c in df.columns]
    df["公司代號"] = df["公司代號"].astype(str).str.strip()
    df = df[df["公司代號"].isin(WATCHLIST)]

    missing = set(WATCHLIST) - set(df["公司代號"])
    if missing:
        print(f"[警告] 找不到這些公司：{sorted(missing)}")

    out = pd.DataFrame({
        "period": df["資料年月"].map(roc_to_period),
        "stock_id": df["公司代號"],
        "company_name": df["公司名稱"].str.strip(),
        "industry": df["產業別"].str.strip(),
        "revenue": to_number(df["營業收入_當月營收"]),
        "revenue_prev_month": to_number(df["營業收入_上月營收"]),
        "revenue_last_year": to_number(df["營業收入_去年當月營收"]),
    })
    # 自己算成長率，不依賴來源欄位
    out["mom_pct"] = (out["revenue"] / out["revenue_prev_month"] - 1) * 100
    out["yoy_pct"] = (out["revenue"] / out["revenue_last_year"] - 1) * 100
    return out.reset_index(drop=True)


def save_processed(df: pd.DataFrame) -> list[Path]:
    """依月份分區存檔，同一個月重跑會覆蓋，不會重複。"""
    paths = []
    for period, group in df.groupby("period"):
        path = PROCESSED_DIR / f"period={period}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        group.to_parquet(path, index=False)
        paths.append(path)
    return paths


def main() -> None:
    run_date = datetime.now().strftime("%Y-%m-%d")
    records = fetch_raw()
    print(f"抓到 {len(records)} 筆，原始檔：{save_raw(records, run_date)}")

    df = transform(records)
    for path in save_processed(df):
        print(f"已存：{path}")
    print(df[["period", "stock_id", "company_name", "revenue", "yoy_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
