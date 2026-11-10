"""把儀表板需要的資料從 DuckDB 匯出成小型 Parquet，放進 dashboard/snapshot/ 跟著 repo 一起部署。

執行（在專案根目錄，dbt build 之後）：python dashboard/export_data.py
Streamlit Cloud 讀不到本機的 DuckDB，所以先匯出一份快照；之後改成從 S3 讀取。
"""
import json
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = Path("data/warehouse.duckdb")
OUT_DIR = Path("dashboard/snapshot")
QUERIES = {
    "layer_month": "select * from mart_layer_month where month >= date '2023-01-01' order by chain, layer, month",
    "events": "select * from mart_news_events order by published_at desc",
    "company_month": "select * from mart_company_month where month >= date '2023-01-01' order by stock_id, month",
}


def llm_eval_summary() -> pd.DataFrame:
    """從逐則評估結果算出各系統的準確率。"""
    ev = pd.read_csv("evaluation/eval_results.csv", encoding="utf-8-sig")
    systems = sorted({c.split("__", 1)[1] for c in ev.columns if "__" in c})
    rows = []
    for s in systems:
        relevant = ev[ev["rel"] == 1]
        rows.append({
            "system": s,
            "relevance": (ev["rel"] == ev[f"rel__{s}"]).mean(),
            "event_type": (relevant["ev"] == relevant[f"ev__{s}"]).mean(),
            "direction": (relevant["dir"] == relevant[f"dir__{s}"]).mean(),
            "n": len(ev),
        })
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    for name, query in QUERIES.items():
        df = con.sql(query).df()
        df.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
        print(f"{name:<14} {len(df):>7,} 列")
    con.close()

    pd.read_csv("analysis/output/lead_lag_results.csv", encoding="utf-8-sig") \
      .to_parquet(OUT_DIR / "lead_lag.parquet", index=False)
    llm_eval_summary().to_parquet(OUT_DIR / "llm_eval.parquet", index=False)

    events = pd.read_parquet(OUT_DIR / "events.parquet")
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "news_from": str(events["published_at"].min())[:10],
        "news_to": str(events["published_at"].max())[:10],
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    size_mb = sum(f.stat().st_size for f in OUT_DIR.iterdir()) / 1e6
    print(f"\n已匯出到 {OUT_DIR}/，共 {size_mb:.1f} MB；新聞期間 {meta['news_from']} ~ {meta['news_to']}")


if __name__ == "__main__":
    main()
