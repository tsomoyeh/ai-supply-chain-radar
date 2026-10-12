"""從公開資訊觀測站（MOPS）補抓歷史月營收，上市（sii）＋上櫃（otc）全市場。

執行範例：
    python ingestion/mops_revenue_backfill.py --start 2026-07 --end 2026-09   # 先小範圍測試
    python ingestion/mops_revenue_backfill.py --start 2021-01                  # 補到上個月

設計重點：
- 抓過的月份會把原始 HTML 存在 data/raw，重跑直接讀快取，不會重抓（可中斷續跑）
- 每次請求間隔數秒，並偵測 MOPS 的封鎖頁面，被擋就立刻停
- 存全市場資料，篩選追蹤清單留到後面的轉換步驟
資料單位：新台幣千元
"""
import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{roc_year}_{month}_0.html"
MARKETS = ["sii", "otc"]  # sii=上市, otc=上櫃
RAW_DIR = Path("data/raw/mops_monthly_revenue")
PROCESSED_DIR = Path("data/processed/mops_monthly_revenue")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research project: ai-supply-chain-radar)"}
SLEEP_SECONDS = 3
RECENT_MONTHS = 2  # 最近的月份可能還有公司沒公布，每次都重抓

# 用來檢查資料完整性的幾家公司
CHECK_IDS = ["2330", "2308", "3711", "6488"]

ROW_RE = re.compile(
    r"<tr align=right><td align=center>\s*([0-9A-Z]{4,6})\s*</td>"
    r"<td align=left>(.*?)</td>(.*?)</tr>",
    re.I | re.S,
)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)


class BlockedError(Exception):
    pass


def raw_path(market: str, period: str) -> Path:
    return RAW_DIR / market / f"{period}.html"


def fetch_bytes(market: str, period: str) -> bytes:
    year, month = map(int, period.split("-"))
    url = URL.format(market=market, roc_year=year - 1911, month=month)
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            content = resp.content
            if b"SECURITY REASONS" in content:
                raise BlockedError(f"被 MOPS 封鎖：{url}")
            time.sleep(SLEEP_SECONDS)
            return content
        except requests.RequestException as e:
            wait = 5 * 2 ** attempt
            print(f"  請求失敗（{e}），{wait} 秒後重試")
            time.sleep(wait)
    raise RuntimeError(f"重試 3 次仍失敗：{url}")


def to_number(text: str):
    text = text.replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse(html: str, market: str, period: str) -> pd.DataFrame:
    rows = []
    for stock_id, name, rest in ROW_RE.findall(html):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in CELL_RE.findall(rest)]
        if len(cells) < 3:
            continue
        rows.append({
            "period": period,
            "market": market,
            "stock_id": stock_id,
            "company_name": re.sub(r"<[^>]+>", "", name).strip(),
            "revenue": to_number(cells[0]),
            "revenue_prev_month": to_number(cells[1]),
            "revenue_last_year": to_number(cells[2]),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["mom_pct"] = (df["revenue"] / df["revenue_prev_month"] - 1) * 100
        df["yoy_pct"] = (df["revenue"] / df["revenue_last_year"] - 1) * 100
    return df


def is_recent(period: str) -> bool:
    cutoff = (pd.Timestamp.today() - pd.DateOffset(months=RECENT_MONTHS)).strftime("%Y-%m")
    return period > cutoff


def load_month(market: str, period: str) -> pd.DataFrame:
    path = raw_path(market, period)
    if path.exists() and not is_recent(period):
        content = path.read_bytes()
    else:
        content = fetch_bytes(market, period)
    df = parse(content.decode("cp950", errors="replace"), market, period)
    # 只有解析得到資料才存快取，避免把空白頁或錯誤頁當成已完成
    if not df.empty:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return df


def main() -> None:
    last_month = (pd.Timestamp.today() - pd.DateOffset(months=1)).strftime("%Y-%m")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01", help="起始月份，例如 2021-01")
    parser.add_argument("--end", default=last_month, help="結束月份，預設為上個月")
    args = parser.parse_args()

    periods = [p.strftime("%Y-%m") for p in pd.period_range(args.start, args.end, freq="M")]
    print(f"準備處理 {len(periods)} 個月 × {len(MARKETS)} 個市場")

    for period in periods:
        frames = []
        counts = []
        try:
            for market in MARKETS:
                df = load_month(market, period)
                counts.append(f"{market} {len(df)} 筆")
                if df.empty:
                    print(f"  [警告] {period} {market} 解析不到資料")
                frames.append(df)
        except BlockedError as e:
            print(f"[停止] {e}。已完成的月份都有快取，晚一點再重跑即可續抓。")
            sys.exit(1)

        month_df = pd.concat(frames, ignore_index=True)
        if month_df.empty:
            continue
        out = PROCESSED_DIR / f"period={period}" / "data.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        month_df.to_parquet(out, index=False)
        found = [s for s in CHECK_IDS if s in set(month_df["stock_id"])]
        print(f"{period}：{'、'.join(counts)}｜檢查公司有出現：{found}")


if __name__ == "__main__":
    main()
