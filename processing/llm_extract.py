"""用 LLM 把新聞標題轉成結構化的供應鏈訊號。

執行：
    python processing/llm_extract.py --limit 80                         # 先測兩批
    python processing/llm_extract.py                                    # 全部（會分好幾天）
    python processing/llm_extract.py --model qwen/qwen3.8-27b --limit 80  # 換模型

設計重點：
- 只處理候選新聞，且每家公司每個時間窗最多 10 則（小公司全收），主題新聞全收
- 每次請求打包 40 則標題，LLM 回傳精簡 JSON，用 Pydantic 逐筆驗證
- 結果逐筆存在 data/raw/llm/<模型>/results.jsonl，已處理的不會重跑，可中斷續跑
- 依伺服器回報的剩餘額度自動等待；每日額度用完就停下，隔天再跑同一行指令
"""
import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, ValidationError
from tqdm import tqdm

FILTERED_PATH = Path("data/processed/news/articles_filtered.parquet")
LINKS_PATH = Path("data/processed/news/article_companies.parquet")
RAW_DIR = Path("data/raw/llm")
OUT_DIR = Path("data/processed/news")

DEFAULT_MODEL = "openai/gpt-oss-120b"
# 服務商都用 OpenAI 相容的 API，換服務商只需要換網址和金鑰
PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
    "deepinfra": {"base_url": "https://api.deepinfra.com/v1/openai", "key_env": "DEEPINFRA_API_KEY"},
    # 透過 OpenRouter 呼叫，固定由 DeepInfra 執行，避免同一批資料被分給不同服務商
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
                   "extra_body": {"provider": {"order": ["deepinfra"], "allow_fallbacks": False}},
                   "reasoning_object": True},
    # 透過 OpenRouter 呼叫 Groq：用 OpenRouter 儲值的額度，不受 Groq 免費方案限制
    "openrouter-groq": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
                        "extra_body": {"provider": {"order": ["groq"], "allow_fallbacks": False}},
                        "reasoning_object": True},
}
CURRENT_PROVIDER = "groq"  # 寫進每筆結果，之後可以追蹤是哪個服務商判斷的
PER_COMPANY_WINDOW_CAP = 10
BATCH_SIZE = 40
MAX_TOKENS = 3000
# 不同模型控制「思考程度」的參數不同，思考越多越慢、越耗 token
MODEL_OPTIONS = {
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
    "openai/gpt-oss-20b": {"reasoning_effort": "low"},
    "qwen/qwen3.8-27b": {"reasoning_effort": "none"},
}

EVENT_TYPES = [
    "demand_up",          # 需求增加、新訂單、出貨成長、拉貨
    "demand_down",        # 需求下修、砍單、出貨衰退、庫存調整
    "capacity_expansion",  # 擴產、新廠、資本支出增加
    "capacity_tight",     # 產能吃緊、缺貨、供不應求
    "price_up",           # 漲價（產品、原料、運價）
    "price_down",         # 降價
    "supply_disruption",  # 停工、災害、斷料、罷工
    "policy_trade",       # 關稅、出口管制、補貼、政府政策
    "financial_report",   # 已公布的營收、財報、EPS（分析時排除，避免資料洩漏）
    "product_tech",       # 新產品、新技術、研發進度
    "other",              # 人事、法律、公益等其他
]
EventType = Literal[tuple(EVENT_TYPES)]

SYSTEM_PROMPT = f"""You classify news headlines about the semiconductor and AI server supply chain
(raw materials, chip manufacturing, packaging, memory, PCB/substrates, server assembly, power,
cooling, logistics, and cloud/AI customers). Headlines may be in Traditional Chinese or English.

For EACH numbered headline, output one object with these keys:
- "i": the headline number
- "rel": 1 if the headline describes business or industry developments that affect supply or
  demand (orders, outlook, capacity, prices, supply disruptions, policy, financial results,
  products). 0 if it is unrelated: job interview posts, executive appointments, ESG/charity/awards,
  company marketing or how-to blog posts, consumer gadget rumors, pure stock-trading talk.
- "ev": one of {EVENT_TYPES}
- "dir": 1 if positive for the companies or industry involved, -1 if negative, 0 if neutral
- "str": 1 = minor, 2 = notable, 3 = major (e.g. big earthquake, sweeping export controls); 0 if rel is 0

Critical rules:
- "financial_report" is ONLY for actual results already reported (last month's revenue,
  quarterly earnings, EPS). Forward-looking guidance, outlooks, forecasts or analyst expectations
  (expects, outlook, guidance, 看俏, 看好, 展望, 預估, 可望) are NOT financial_report:
  use demand_up / demand_down (or price_up / price_down) instead.
- Executive appointments, ESG, awards and job posts are "other" with rel 0.

Examples:
- "緯穎營收看俏 AI伺服器出貨續強" -> ev "demand_up", dir 1
- "Foxconn expects sales to fall as iPhone doubts grow" -> ev "demand_down", dir -1
- "台積電12月營收年增8% 全年營收創新高" -> ev "financial_report", dir 1
- "Former Bosch executive heads TSMC's German unit" -> ev "other", rel 0, dir 0
- "ABF載板供不應求 欣興南電擴產" -> ev "capacity_tight", dir 1

Reply with JSON only, in exactly this shape: {{"results": [{{"i": 1, "rel": 1, "ev": "demand_up", "dir": 1, "str": 2}}, ...]}}
Include every headline number exactly once."""


class Signal(BaseModel):
    i: int
    rel: Literal[0, 1]
    ev: EventType
    dir: Literal[-1, 0, 1]
    strength: Literal[0, 1, 2, 3] = Field(alias="str")  # 0 = 不相關，沒有強度可言


def make_client(provider: str):
    from openai import OpenAI
    global CURRENT_PROVIDER
    CURRENT_PROVIDER = provider
    cfg = PROVIDERS[provider]
    return OpenAI(base_url=cfg["base_url"], api_key=os.environ[cfg["key_env"]], max_retries=0)


def model_slug(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "_", model)


def select_articles() -> pd.DataFrame:
    """候選新聞抽樣：每家公司每個時間窗最多 N 則。用 article_id 排序取前 N，結果每次都一樣。"""
    a = pd.read_parquet(FILTERED_PATH)
    links = pd.read_parquet(LINKS_PATH)
    cand = a[a["candidate"]]
    cl = links.merge(cand[["article_id", "window_start"]], on="article_id").sort_values("article_id")
    picked = set(cl.groupby(["stock_id", "window_start"]).head(PER_COMPANY_WINDOW_CAP)["article_id"])
    topic_only = set(cand.loc[(cand["n_companies"] == 0) & cand["topic_match"], "article_id"])
    selected = cand[cand["article_id"].isin(picked | topic_only)]
    return selected.sort_values("published_at")[["article_id", "title", "published_at"]]


def load_done(results_path: Path) -> set:
    if not results_path.exists():
        return set()
    with results_path.open(encoding="utf-8") as f:
        return {json.loads(line)["article_id"] for line in f if line.strip()}


def parse_reset(value: str) -> float:
    """把 '1m26.4s'、'1.387s'、'250ms' 這類時間字串轉成秒數。"""
    if not value:
        return 0.0
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


class DailyLimitReached(Exception):
    pass


def call_llm(client, model: str, titles: list) -> tuple:
    import openai as groq  # 錯誤類別名稱與 groq 套件相同

    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))
    opts = dict(MODEL_OPTIONS.get(model, {}))
    cfg = PROVIDERS[CURRENT_PROVIDER]
    extra = dict(cfg.get("extra_body", {}))
    if cfg.get("reasoning_object") and "reasoning_effort" in opts:
        # OpenRouter 用 reasoning 物件設定思考程度
        extra["reasoning"] = {"effort": opts.pop("reasoning_effort")}
    for attempt in range(5):
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": numbered}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=MAX_TOKENS,
                **opts,
                extra_body=extra or None,
            )
            return raw.parse(), raw.headers
        except groq.RateLimitError as e:
            wait = parse_reset(e.response.headers.get("retry-after", "") + "s") or 30
            if wait > 600:
                raise DailyLimitReached(f"需要等 {wait / 3600:.1f} 小時")
            tqdm.write(f"  被限速，等 {wait:.0f} 秒")
            time.sleep(wait + 1)
        except groq.PermissionDeniedError:
            wait = 60 * (attempt + 1)
            tqdm.write(f"  連線被拒（403，通常是網路問題），{wait} 秒後重試")
            time.sleep(wait)
        except (groq.APIConnectionError, groq.InternalServerError) as e:
            wait = 10 * 2 ** attempt
            tqdm.write(f"  連線或伺服器錯誤（{type(e).__name__}），{wait} 秒後重試")
            time.sleep(wait)
    raise RuntimeError("重試多次仍失敗")


def process_batch(client, model: str, batch: pd.DataFrame, results_path: Path, errors_path: Path) -> tuple:
    resp, headers = call_llm(client, model, batch["title"].tolist())
    content = resp.choices[0].message.content
    usage = resp.usage.total_tokens if resp.usage else 0
    ok = 0
    try:
        items = extract_json(content).get("results", [])
    except (ValueError, AttributeError):
        items = []
        with errors_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"error": "invalid_json", "content": content}, ensure_ascii=False) + "\n")

    ids = batch["article_id"].tolist()
    seen = set()
    with results_path.open("a", encoding="utf-8") as f:
        for item in items:
            try:
                s = Signal.model_validate(item)
            except ValidationError as e:
                with errors_path.open("a", encoding="utf-8") as ef:
                    ef.write(json.dumps({"error": "validation", "item": item, "detail": str(e)[:300]},
                                        ensure_ascii=False) + "\n")
                continue
            if not 1 <= s.i <= len(ids) or s.i in seen:
                continue
            seen.add(s.i)
            f.write(json.dumps({
                "article_id": ids[s.i - 1], "relevant": s.rel, "event_type": s.ev,
                "direction": s.dir, "strength": s.strength, "model": model, "provider": CURRENT_PROVIDER,
            }, ensure_ascii=False) + "\n")
            ok += 1

    # 依伺服器回報的剩餘 token 決定要不要先等一下（每分鐘 token 上限）
    remaining = int(headers.get("x-ratelimit-remaining-tokens", "99999") or 99999)
    if remaining < MAX_TOKENS + 2000:
        wait = parse_reset(headers.get("x-ratelimit-reset-tokens", "")) + 1
        time.sleep(wait)
    return ok, usage


def build_output(results_path: Path, model: str) -> None:
    if not results_path.exists():
        return
    res = pd.read_json(results_path, lines=True).drop_duplicates("article_id", keep="last")
    a = pd.read_parquet(FILTERED_PATH)[["article_id", "title", "published_at", "source", "lang", "link"]]
    out = res.merge(a, on="article_id", how="left")
    path = OUT_DIR / f"llm_signals_{model_slug(model)}.parquet"
    out.to_parquet(path, index=False)
    print(f"\n已輸出 {len(out):,} 筆到 {path}")
    print("\n事件類型分布：")
    print(out["event_type"].value_counts().to_string())
    print(f"\n判定為相關的比例：{out['relevant'].mean():.0%}")


def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default="groq", choices=list(PROVIDERS))
    parser.add_argument("--limit", type=int, help="這次最多處理幾則（測試用）")
    args = parser.parse_args()

    load_dotenv(".env")
    client = make_client(args.provider)

    run_dir = RAW_DIR / model_slug(args.model)
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path, errors_path = run_dir / "results.jsonl", run_dir / "errors.jsonl"

    selected = select_articles()
    done = load_done(results_path)
    todo = selected[~selected["article_id"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"抽樣後共 {len(selected):,} 則，已完成 {len(done):,}，這次處理 {len(todo):,} 則"
          f"（模型：{args.model}，服務商：{args.provider}）")

    total_ok = total_tokens = 0
    # 進度條從整體進度算起，中斷後續跑會接著上次的位置
    bar = tqdm(total=len(done) + len(todo), initial=len(done), unit="則", desc="LLM 判斷",
               bar_format="{desc} {bar} {percentage:3.0f}% {n_fmt}/{total_fmt} "
                          "[已用 {elapsed}，預估剩 {remaining}] {postfix}")
    try:
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo.iloc[start:start + BATCH_SIZE]
            ok, tokens = process_batch(client, args.model, batch, results_path, errors_path)
            total_ok += ok
            total_tokens += tokens
            bar.update(len(batch))
            bar.set_postfix_str(f"本批成功 {ok}/{len(batch)}，累計 {total_tokens:,} tokens")
    except DailyLimitReached as e:
        print(f"[停止] 今天的額度用完了（{e}）。已完成的都有存檔，明天再跑同一行指令即可。")
    except KeyboardInterrupt:
        print("\n[中斷] 已完成的都有存檔。")

    bar.close()
    print(f"\n這次成功 {total_ok:,} 則，平均每則 {total_tokens / max(total_ok, 1):.0f} tokens")
    build_output(results_path, args.model)


if __name__ == "__main__":
    main()
