"""新聞過濾與公司比對：把 Google News 抓回來的新聞，整理成可以交給 LLM 的候選清單。

執行：python processing/filter_news.py

三個步驟：
1. 跨查詢去重：同一則新聞可能被好幾個查詢抓到，只留一份
2. 標題比對：標題有提到哪些公司（一則新聞可以對應多家）、或提到哪個產業主題
3. 標記股市盤勢類標題（買超、漲停、目標價⋯⋯），這類講的是股票交易而不是產業動態

這一版只「標記」不刪除，先看統計和抽樣，確認規則合理後再決定要排除哪些。
"""
import re
from pathlib import Path

import pandas as pd

ARTICLES_PATH = Path("data/processed/news/articles.parquet")
COMPANIES_PATH = Path("config/companies.csv")
QUERIES_PATH = Path("config/news_queries.csv")
OUT_ARTICLES = Path("data/processed/news/articles_filtered.parquet")
OUT_LINKS = Path("data/processed/news/article_companies.parquet")

MARKET_NOISE = [
    # 中文：股票交易、盤勢、投資建議
    # 注意：不放「上漲」「大漲」這類詞，因為「運價上漲」「記憶體價格大漲」是重要的產業訊號
    "買超", "賣超", "三大法人", "外資", "投信", "自營商", "融資", "融券", "當沖",
    "漲停", "跌停", "股價", "目標價", "台股", "概念股", "熱門股", "強勢股", "飆股", "存股",
    "盤中", "盤前", "盤後", "開盤", "收盤", "加權指數", "權證", "ETF",
    "除權", "除息", "殖利率", "配息", "股利", "技術分析", "均線", "K線",
    # 人工標註時發現的漏網詞
    "焦點股", "天價", "違約交割", "千金股", "萬金股", "股王", "投資首選", "護盤", "換股", "國安基金",
    # 英文
    "stock", "shares", "price target", "buy rating", "sell rating", "rally", "should you buy",
    "dividend", "ETF", "Motley Fool",
]


def keyword_pattern(keywords: list) -> re.Pattern:
    parts = []
    for k in keywords:
        k = k.strip()
        if not k:
            continue
        # 英文以完整單字比對，避免 Meta 比對到 Metal；中文直接比對字串
        parts.append(rf"\b{re.escape(k)}\b" if k.isascii() else re.escape(k))
    return re.compile("|".join(parts), re.IGNORECASE)


def split(value) -> list:
    return [v for v in str(value).split("|") if v.strip()] if isinstance(value, str) else []


def main() -> None:
    articles = pd.read_parquet(ARTICLES_PATH)
    companies = pd.read_csv(COMPANIES_PATH, dtype=str)
    queries = pd.read_csv(QUERIES_PATH, dtype=str)
    total = len(articles)

    # 1. 跨查詢去重：同一個連結只留一份，記下是哪些查詢抓到的
    query_ids = articles.groupby("article_id")["query_id"].agg(lambda s: "|".join(sorted(set(s))))
    articles = (articles.sort_values("published_at")
                .drop_duplicates("article_id")
                .drop(columns=["query_id", "stock_id"])
                .set_index("article_id"))
    articles["query_ids"] = query_ids
    articles = articles.reset_index()

    # 2a. 公司比對（一則新聞可以對應多家公司）
    links = []
    for c in companies.itertuples():
        include = keyword_pattern(split(c.title_keywords))
        exclude = keyword_pattern(split(c.title_exclude)) if split(c.title_exclude) else None
        hit = articles["title"].str.contains(include)
        if exclude is not None:
            hit &= ~articles["title"].str.contains(exclude)
        for aid in articles.loc[hit, "article_id"]:
            links.append({"article_id": aid, "stock_id": c.stock_id})
    links = pd.DataFrame(links)
    n_companies = links.groupby("article_id").size()
    articles["n_companies"] = articles["article_id"].map(n_companies).fillna(0).astype(int)

    # 2b. 主題比對：主題查詢抓到的新聞，標題要真的包含主題詞才算
    topics = queries[queries["stock_id"].isna()]
    articles["topic_match"] = False
    for t in topics.itertuples():
        from_topic = articles["query_ids"].str.contains(rf"(?:^|\|){re.escape(t.query_id)}(?:\||$)")
        in_title = articles["title"].str.contains(keyword_pattern(split(t.terms)))
        articles.loc[from_topic & in_title, "topic_match"] = True

    # 3. 股市盤勢類標題
    articles["is_market_noise"] = articles["title"].str.contains(keyword_pattern(MARKET_NOISE))

    articles["relevant"] = (articles["n_companies"] > 0) | articles["topic_match"]
    articles["candidate"] = articles["relevant"] & ~articles["is_market_noise"]

    OUT_ARTICLES.parent.mkdir(parents=True, exist_ok=True)
    articles.to_parquet(OUT_ARTICLES, index=False)
    links.to_parquet(OUT_LINKS, index=False)

    # ---- 報告 ----
    rel = articles["relevant"]
    print(f"抓到的新聞（含跨查詢重複）：{total:,}")
    print(f"跨查詢去重後：{len(articles):,}")
    print(f"標題提到追蹤公司或主題：{rel.sum():,}（{rel.mean():.0%}）")
    print(f"  其中屬於股市盤勢類：{(rel & articles['is_market_noise']).sum():,}")
    print(f"最終候選（交給 LLM）：{articles['candidate'].sum():,}")

    cand_links = links[links["article_id"].isin(articles.loc[articles["candidate"], "article_id"])]
    per_company = (cand_links.merge(companies[["stock_id", "name_zh"]], on="stock_id")
                   .groupby(["stock_id", "name_zh"]).size().sort_values())
    print("\n各公司候選新聞數（由少到多）：")
    print(per_company.to_string())

    print(f"\n主題新聞（標題含主題詞、且未對應任何公司）：{(articles['topic_match'] & (articles['n_companies'] == 0) & articles['candidate']).sum():,}")

    def sample_titles(df: pd.DataFrame, n: int = 12) -> str:
        return "\n".join(df.sample(n=min(n, len(df)), random_state=42)["title"])

    print("\n=== 抽樣：最終候選 ===")
    print(sample_titles(articles[articles["candidate"]]))
    print("\n=== 抽樣：被標為股市盤勢 ===")
    print(sample_titles(articles[rel & articles["is_market_noise"]]))


if __name__ == "__main__":
    main()
