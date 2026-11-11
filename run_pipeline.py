"""依序執行整條資料管線，任何一步失敗就停止。本機和 GitHub Actions 都用這一支。

執行（在專案根目錄）：python run_pipeline.py
"""
import os
import subprocess
import sys
import time
from datetime import date

import pandas as pd

# 營收只需要重抓最近 3 個月；更早的月份快取已經完整
revenue_start = (pd.Timestamp(date.today()) - pd.DateOffset(months=3)).strftime("%Y-%m")
provider = os.environ.get("LLM_PROVIDER", "openrouter-groq")

STEPS = [
    ("月營收", ["python", "ingestion/mops_revenue_backfill.py", "--start", revenue_start], "."),
    ("新聞", ["python", "ingestion/google_news.py"], "."),
    ("原物料價格", ["python", "ingestion/fred_commodities.py"], "."),
    ("新聞過濾", ["python", "processing/filter_news.py"], "."),
    ("LLM 判斷", ["python", "processing/llm_extract.py", "--provider", provider], "."),
    ("dbt 建模與測試", ["dbt", "build", "--profiles-dir", "."], "transform"),
    ("匯出儀表板資料", ["python", "dashboard/export_data.py"], "."),
]


def main() -> None:
    started = time.time()
    for i, (name, cmd, cwd) in enumerate(STEPS, start=1):
        print(f"\n===== {i}/{len(STEPS)} {name} =====", flush=True)
        t = time.time()
        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            print(f"\n[失敗] 第 {i} 步「{name}」結束代碼 {result.returncode}，管線停止。")
            sys.exit(result.returncode)
        print(f"----- {name} 完成，{time.time() - t:.0f} 秒")
    print(f"\n全部完成，共 {(time.time() - started) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
