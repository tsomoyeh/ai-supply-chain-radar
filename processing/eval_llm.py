"""LLM 準確度評估：用人工標註的 100 則新聞，比較不同模型和關鍵字規則的準確率。

步驟：
    python processing/eval_llm.py sheet                            # 1. 抽 100 則，產生標註表
    （用 Excel 或 Numbers 打開 evaluation/labels.csv，填寫 rel、ev、dir、str、full_text_changes）
    python processing/eval_llm.py run --model openai/gpt-oss-120b  # 2. 讓模型判斷同一批新聞
    python processing/eval_llm.py run --model qwen/qwen3.8-27b
    python processing/eval_llm.py score                            # 3. 計算準確率

設計重點：
- 排除調整指示時看過的新聞，避免「拿考古題考試」
- 標註表不顯示模型答案，避免人工標註被模型影響（錨定偏誤）
- 附上關鍵字規則當基準，證明 LLM 確實比簡單規則好
"""
import argparse
import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import llm_extract as L  # noqa: E402

EVAL_DIR = Path("evaluation")
LABELS_PATH = EVAL_DIR / "labels.csv"
RESULTS_PATH = EVAL_DIR / "eval_results.csv"
EVAL_RAW_DIR = Path("data/raw/llm_eval")
TUNING_RESULTS = L.RAW_DIR / L.model_slug(L.DEFAULT_MODEL) / "results.jsonl"
N_PER_LANG = 50
LABEL_COLS = ["rel", "ev", "dir", "str", "full_text_changes", "note"]


# ---------- 1. 產生標註表 ----------
def make_sheet() -> None:
    if LABELS_PATH.exists():
        raise SystemExit(f"{LABELS_PATH} 已存在，為避免覆蓋你的標註，請先手動刪除或改名")
    selected = L.select_articles()
    tuning_ids = L.load_done(TUNING_RESULTS)  # 調整指示時看過的新聞
    pool = selected[~selected["article_id"].isin(tuning_ids)]
    meta = pd.read_parquet(L.FILTERED_PATH)[["article_id", "lang", "link"]]
    pool = pool.merge(meta, on="article_id")
    parts = [g.sample(min(N_PER_LANG, len(g)), random_state=7) for _, g in pool.groupby("lang")]
    sample = pd.concat(parts).sample(frac=1, random_state=7)  # 打亂順序，中英文交錯
    sheet = sample[["article_id", "lang", "title", "link"]].copy()
    sheet.insert(2, "date", sample["published_at"].dt.strftime("%Y-%m-%d"))
    for c in LABEL_COLS:
        sheet[c] = ""
    # 標題後面緊接著要填的欄位，連結很長，放到最後面
    sheet = sheet[["title", *LABEL_COLS, "link", "date", "lang", "article_id"]]
    EVAL_DIR.mkdir(exist_ok=True)
    sheet.to_csv(LABELS_PATH, index=False, encoding="utf-8-sig")  # utf-8-sig 讓 Excel 正確顯示中文
    print(f"已產生 {LABELS_PATH}：{len(sheet)} 則（{sheet['lang'].value_counts().to_dict()}）")


# ---------- 2. 讓模型判斷 ----------
def run_model(model: str, provider: str) -> None:
    from dotenv import load_dotenv

    load_dotenv(".env")
    client = L.make_client(provider)
    labels = pd.read_csv(LABELS_PATH, dtype=str, encoding="utf-8-sig")
    name = model if provider == "groq" else f"{provider}/{model}"
    run_dir = EVAL_RAW_DIR / L.model_slug(name)
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path, errors_path = run_dir / "results.jsonl", run_dir / "errors.jsonl"
    todo = labels[~labels["article_id"].isin(L.load_done(results_path))]
    print(f"{provider} {model}：還有 {len(todo)} 則要判斷")
    for start in range(0, len(todo), L.BATCH_SIZE):
        batch = todo.iloc[start:start + L.BATCH_SIZE]
        ok, tokens = L.process_batch(client, model, batch, results_path, errors_path)
        print(f"  本批成功 {ok}/{len(batch)}，{tokens:,} tokens")
    missing = len(labels) - len(L.load_done(results_path))
    print("全部完成" if missing == 0 else f"還有 {missing} 則失敗，再跑一次同一行指令會補做")


# ---------- 關鍵字規則基準 ----------
POS = ["看好", "看俏", "成長", "創高", "新高", "擴產", "增產", "漲價", "調漲", "訂單", "拉貨", "強勁",
       "大單", "供不應求", "可望", "rise", "surge", "growth", "record", "expand", "strong", "boost", "wins"]
NEG = ["下修", "衰退", "砍單", "減產", "降價", "下滑", "疲弱", "虧損", "停工", "地震", "管制", "延後",
       "fall", "drop", "cut", "decline", "weak", "loss", "ban", "curb", "slump", "delay", "halt"]
EV_RULES = [  # 依序比對，第一個命中的就是答案
    ("financial_report", r"營收|EPS|財報|獲利|revenue|earnings|profit"),
    ("supply_disruption", r"停工|地震|火災|停電|斷料|earthquake|outage|disruption"),
    ("policy_trade", r"關稅|出口管制|補貼|禁令|制裁|tariff|export control|sanction|subsid"),
    ("capacity_tight", r"供不應求|缺貨|吃緊|shortage|tight"),
    ("price_up", r"漲價|調漲|price hike|raise prices"),
    ("price_down", r"降價|price cut|discount"),
    ("demand_down", r"砍單|下修|衰退|減產|weak demand|cut orders"),
    ("capacity_expansion", r"擴產|新廠|蓋廠|設廠|資本支出|購地|expand|new plant|factory|acres|invest"),
    ("demand_up", r"訂單|拉貨|出貨|需求|大單|orders|demand|shipments"),
    ("product_tech", r"推出|發表|新品|技術|奈米|launch|unveil|introduce"),
]


def baseline(title: str) -> dict:
    t = str(title)
    score = sum(w.lower() in t.lower() for w in POS) - sum(w.lower() in t.lower() for w in NEG)
    ev = next((name for name, pat in EV_RULES if re.search(pat, t, re.I)), "other")
    direction = (score > 0) - (score < 0)
    return {"rel": int(ev != "other" or direction != 0), "ev": ev, "dir": direction}


# ---------- 3. 計算準確率 ----------
def score() -> None:
    labels = pd.read_csv(LABELS_PATH, dtype=str, encoding="utf-8-sig")
    for c in ["rel", "dir", "str"]:
        labels[c] = pd.to_numeric(labels[c], errors="coerce")
    labels["ev"] = labels["ev"].str.strip()
    filled = labels.dropna(subset=["rel"])
    bad_ev = filled[(filled["rel"] == 1) & ~filled["ev"].isin(L.EVENT_TYPES)]
    if len(bad_ev):
        print("[注意] 這些列的 ev 不在允許清單內，請修正：")
        print(bad_ev[["title", "ev"]].to_string())
    print(f"已標註 {len(filled)}/{len(labels)} 則\n")

    systems = {"關鍵字規則": pd.DataFrame([{"article_id": r.article_id, **baseline(r.title)}
                                       for r in filled.itertuples()])}
    for d in sorted(EVAL_RAW_DIR.glob("*/results.jsonl")):
        res = pd.read_json(d, lines=True).drop_duplicates("article_id", keep="last")
        systems[d.parent.name] = res.rename(columns={"relevant": "rel", "event_type": "ev",
                                                    "direction": "dir"})[["article_id", "rel", "ev", "dir"]]

    rows, detail = [], filled[["article_id", "lang", "title", "rel", "ev", "dir"]].copy()
    for name, pred in systems.items():
        m = filled.merge(pred, on="article_id", suffixes=("", "_pred"))
        rel_m = m[m["rel"] == 1]
        fin = m[(m["ev"] == "financial_report") | (m["ev_pred"] == "financial_report")]
        rows.append({
            "系統": name,
            "判斷數": len(m),
            "相關性準確率": (m["rel"] == m["rel_pred"]).mean(),
            "事件類型準確率": (rel_m["ev"] == rel_m["ev_pred"]).mean(),
            "方向準確率": (rel_m["dir"] == rel_m["dir_pred"]).mean(),
            "財報類一致率": (fin["ev"] == fin["ev_pred"]).mean() if len(fin) else float("nan"),
            "中文事件準確率": (rel_m[rel_m["lang"] == "zh"]["ev"] == rel_m[rel_m["lang"] == "zh"]["ev_pred"]).mean(),
            "英文事件準確率": (rel_m[rel_m["lang"] == "en"]["ev"] == rel_m[rel_m["lang"] == "en"]["ev_pred"]).mean(),
        })
        detail = detail.merge(pred.add_suffix(f"__{name}").rename(columns={f"article_id__{name}": "article_id"}),
                              on="article_id", how="left")

    table = pd.DataFrame(rows).set_index("系統")
    pct_cols = [c for c in table.columns if c != "判斷數"]
    print(table.to_string(formatters={c: "{:.0%}".format for c in pct_cols}))
    print("（事件類型、方向只計算你標為相關的新聞）")

    # 分組比較：人工獨立標註 vs Claude 預標後人工審核
    src = filled["note"].fillna("").str.contains("Claude預標").map({True: "Claude預標", False: "人工獨立"})
    print("\n事件類型準確率，按標註來源分組：")
    for name, pred in systems.items():
        m = filled.assign(src=src).merge(pred, on="article_id", suffixes=("", "_pred"))
        m = m[m["rel"] == 1]
        parts = [f"{g} {(d['ev'] == d['ev_pred']).mean():.0%}（{len(d)} 則）" for g, d in m.groupby("src")]
        print(f"  {name}：" + "，".join(parts))

    ftc = filled["full_text_changes"].str.upper().str.strip()
    if ftc.isin(["Y", "N"]).any():
        share = (ftc == "Y").sum() / ftc.isin(["Y", "N"]).sum()
        print(f"\n讀完全文後判斷會改變的比例：{share:.0%}（代表只看標題會損失多少資訊）")

    detail.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n逐則比較已存到 {RESULTS_PATH}，可以用 Excel 打開看每個系統錯在哪裡")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sheet")
    run = sub.add_parser("run")
    run.add_argument("--model", required=True)
    run.add_argument("--provider", default="groq", choices=list(L.PROVIDERS))
    sub.add_parser("score")
    args = parser.parse_args()
    if args.cmd == "sheet":
        make_sheet()
    elif args.cmd == "run":
        run_model(args.model, args.provider)
    else:
        score()


if __name__ == "__main__":
    main()
