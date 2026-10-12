"""從 Google News RSS 按兩週一個時間窗、按公司與主題抓英文新聞標題。

執行：
    python ingestion/google_news.py --start 2024-01-01 --end 2024-01-28   # 先測一個月
    python ingestion/google_news.py --start 2024-01-01                     # 完整回補，約 2 小時

設計重點：
- 查詢字串放在 config/news_queries.csv，調整查詢不用改程式
- 原始 RSS 快取在 data/raw，可中斷續跑；最近 3 週每次重抓
- 用 curl 送請求（這台電腦的 Python 加密函式庫太舊，容易被當成機器人）
- 遇到限速自動拉長等待；回傳的不是 RSS（例如驗證頁面）就停下
- 所有原始檔合併、去重後輸出一份 Parquet
"""
import argparse
import hashlib
import html
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

QUERIES_PATH = Path("config/news_queries.csv")
RAW_DIR = Path("data/raw/google_news")
PROCESSED_PATH = Path("data/processed/news/articles.parquet")
WINDOW_DAYS = 14
SLEEP_SECONDS = 2.5
RECENT_DAYS = 21
LANG_PARAMS = {
    "en": "hl=en-US&gl=US&ceid=US:en",
    "zh": "hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
}
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


class BlockedError(Exception):
    pass


def build_query(terms: str, must_include) -> str:
    parts = [f'"{t.strip()}"' for t in terms.split("|")]
    q = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    if isinstance(must_include, str) and must_include.strip():
        q += f' "{must_include.strip()}"'
    return q


def window_starts(start: str, end: str) -> list:
    first = pd.Timestamp(start)
    first -= timedelta(days=first.weekday())  # 對齊到週一
    return list(pd.date_range(first, pd.Timestamp(end), freq=f"{WINDOW_DAYS}D"))


def fetch(query: str, lang: str, window_start: pd.Timestamp) -> str:
    window_end = window_start + timedelta(days=WINDOW_DAYS)
    q = f"{query} after:{window_start:%Y-%m-%d} before:{window_end:%Y-%m-%d}"
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&{LANG_PARAMS[lang]}"
    cmd = ["curl", "-s", "-L", "--max-time", "60", "-A", USER_AGENT, "-w", "\n%{http_code}", url]
    for attempt in range(4):
        result = subprocess.run(cmd, capture_output=True, text=True)
        time.sleep(SLEEP_SECONDS)
        body, _, status = result.stdout.rpartition("\n")
        if result.returncode != 0 or not status.isdigit():
            wait = 15 * 2 ** attempt
            print(f"  連線失敗（curl 代碼 {result.returncode}），{wait} 秒後重試")
            time.sleep(wait)
            continue
        if status in ("429", "503"):
            wait = 60 * 2 ** attempt
            print(f"  被限速（{status}），{wait} 秒後重試")
            time.sleep(wait)
            continue
        if status != "200" or "<rss" not in body[:500]:
            raise BlockedError(f"HTTP {status}，回傳內容不是 RSS：{body[:150]}")
        return body
    raise BlockedError("重試多次仍被限速")


def load_window(query_id: str, query: str, lang: str, window_start: pd.Timestamp) -> int:
    path = RAW_DIR / query_id / f"{window_start:%Y-%m-%d}.xml"
    is_recent = window_start > pd.Timestamp.today() - timedelta(days=RECENT_DAYS)
    if path.exists() and not is_recent:
        return -1  # 用快取
    body = fetch(query, lang, window_start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return body.count("<item>")


def parse_items(xml_text: str) -> list:
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        title = html.unescape(item.findtext("title", default="")).strip()
        # Google 的標題格式是「標題 - 來源」，把來源拆掉
        if source and title.endswith(f" - {source}"):
            title = title[: -len(f" - {source}")].strip()
        pub = item.findtext("pubDate")
        items.append({
            "title": title,
            "link": item.findtext("link"),
            "published_at": parsedate_to_datetime(pub).replace(tzinfo=None) if pub else None,
            "source": source,
            "source_url": source_el.get("url") if source_el is not None else None,
        })
    return items


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", " ", str(title).lower()).strip()


def build_processed(queries: pd.DataFrame) -> None:
    meta = queries.set_index("query_id")
    rows = []
    for path in sorted(RAW_DIR.glob("*/*.xml")):
        query_id = path.parent.name
        if query_id not in meta.index:
            continue
        for it in parse_items(path.read_text(encoding="utf-8")):
            it.update({
                "query_id": query_id,
                "layer": meta.at[query_id, "layer"],
                "lang": meta.at[query_id, "lang"],
                "stock_id": meta.at[query_id, "stock_id"],
                "window_start": path.stem,
            })
            rows.append(it)
    if not rows:
        print("沒有任何新聞資料")
        return

    df = pd.DataFrame(rows)
    raw_count = len(df)
    df["title_norm"] = df["title"].map(normalize_title)
    df = df[df["title_norm"] != ""].sort_values("published_at")
    # 同一個查詢內，網址或標題重複（轉載、相鄰時間窗重疊）只留最早一筆
    df = df.drop_duplicates(subset=["query_id", "link"])
    df = df.drop_duplicates(subset=["query_id", "title_norm"])
    df["article_id"] = df["link"].map(lambda u: hashlib.sha1(str(u).encode()).hexdigest()[:16])
    df = df.drop(columns="title_norm").reset_index(drop=True)

    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROCESSED_PATH, index=False)
    print(f"\n原始 {raw_count} 筆 → 去重後 {len(df)} 筆，已存：{PROCESSED_PATH}")

    windows = df.groupby("query_id")["window_start"].nunique()
    per_window = (df.groupby("query_id").size() / windows).round(1).sort_values()
    print("\n各查詢每個時間窗平均篇數（由少到多，少的可以考慮合併）：")
    print(per_window.to_string())
    print("\n最常見的新聞來源：")
    print(df["source"].value_counts().head(10).to_string())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--only", nargs="*", help="只跑指定的 query_id")
    args = parser.parse_args()

    queries = pd.read_csv(QUERIES_PATH, dtype=str)
    todo = queries if not args.only else queries[queries["query_id"].isin(args.only)]
    windows = window_starts(args.start, args.end)
    print(f"準備處理 {len(windows)} 個時間窗 × {len(todo)} 個查詢 = {len(windows) * len(todo)} 次")

    try:
        for window_start in windows:
            fetched = cached = 0
            for row in todo.itertuples():
                n = load_window(row.query_id, build_query(row.terms, row.must_include), row.lang, window_start)
                if n < 0:
                    cached += 1
                else:
                    fetched += 1
            print(f"{window_start:%Y-%m-%d}：新抓 {fetched}、快取 {cached}")
    except BlockedError as e:
        print(f"[停止] {e}\n已完成的部分都有快取，晚一點再跑同一行指令會接著抓。")
        build_processed(queries)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[中斷] 已完成的部分都有快取。")
        sys.exit(1)

    build_processed(queries)


if __name__ == "__main__":
    main()
