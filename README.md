# AI Supply Chain Radar

A data pipeline that tracks the semiconductor and AI server supply chain — from raw materials to cloud customers — by turning news headlines into structured signals and testing them against hard data: Taiwan monthly revenue, commodity prices, and more.

**Research question:** Do supply-chain signals extracted from news lead monthly revenue, which is only published about 10 days after each month ends?

**Answer (so far): No.** Under success criteria fixed *before* looking at the results, no layer of the supply chain showed a credible lead. News tone mostly moves *with* the cycle rather than ahead of it. The pipeline is therefore positioned as a near-real-time monitoring tool rather than a forecasting tool. Details in [Results](#results).

## Why this question

Taiwan is unusual: listed companies must publish revenue every month, which makes it possible to observe the AI server boom almost in real time — but still with a lag of up to six weeks. Daily news reports orders, capacity expansions, price changes and export controls long before those show up in revenue. If any of that information arrives early, it should be measurable.

## Results

### LLM classification quality

100 headlines (50 Chinese, 50 English) were labeled by hand and used to compare systems. Headlines used while tuning the prompt were excluded from the evaluation set.

| System | Relevance | Event type | Direction |
|---|---|---|---|
| Keyword rules (baseline) | 68% | 32% | 26% |
| gpt-oss-120b on Groq | 89% | 73% | 91% |
| gpt-oss-120b via OpenRouter → Groq | 90% | 71% | 92% |
| gpt-oss-120b via OpenRouter → DeepInfra | 78% | 56% | 77% |
| qwen3.8-27b on Groq | 88% | 59% | 86% |

*Event type and direction are measured on headlines labeled as relevant.*

Key findings:
- An LLM is necessary: keyword rules can roughly tell whether a headline is relevant, but not what happened or whether it is good or bad news.
- **The same open-weight model scored 17 points lower on event type when served by a different provider.** Any provider change was therefore re-evaluated before use.
- Weakest category: distinguishing already-reported results (`financial_report`) from forward-looking guidance (67% agreement). This matters because reported results are excluded from the signal to avoid leakage (see below).

Labeling method, stated plainly: 25 headlines were labeled independently by me; 75 were pre-labeled by Claude and then reviewed by me, with no changes made. Because reviewing pre-labels invites anchoring, accuracy is also reported separately for the two groups; gpt-oss-120b scored *higher* on the independently labeled group (85% vs 70% on event type), so there is no sign that the pre-labels favored the models. The independent group is small (13 relevant headlines).

### Lead–lag analysis

Monthly signals per supply-chain layer were compared with the layer's revenue growth, shifting the signal from 3 months behind to 6 months ahead. Two comparisons were made:
- **Level:** signal vs year-over-year revenue growth. Both series trend upward during the AI boom, so correlations here are inflated.
- **Change:** month-over-month change in the signal vs change in revenue growth. This removes the shared trend and is the basis for conclusions.

**Success criteria, fixed in advance:** in the change comparison, a lead of 1–3 months with |Spearman r| ≥ 0.4, the same direction at neighboring lags, and agreement between at least two signal definitions, in at least one layer.

**Outcome: not met in any layer.**
- The only |r| ≥ 0.4 at a 1–3 month lead (upstream, share of positive news, r = −0.53 at 1 month) has the opposite sign at neighboring lags, is not supported by other signal definitions, and has no plausible economic direction. With 320 comparisons, a few such values are expected by chance.
- The closest candidate (logistics, 1-month lead) reached r = 0.36 and 0.32 on two definitions, below the threshold and not persistent across lags.
- In the level comparison, news *volume* correlates strongly with revenue (up to 0.81), but almost equally at every lag — the signature of two trending series, not of a lead. A synthetic test with a planted 2-month lead showed the method recovers a true lead clearly (r = 0.94 at exactly 2 months), so the null result is not a failure of the method.

**Interpretation:** financial media mostly report what is happening or has happened; the genuinely forward-looking information (customer forecasts, order books) rarely appears in headlines. Logistics is a possible exception worth watching: news tone and shipping revenue move roughly together, consistent with freight-rate news being reported in real time.

**Next validation:** the pipeline keeps collecting data. Any new signal definition will be tested only on months collected *after* this analysis, to avoid tuning the question to the answer.

## Architecture

```
Sources                      Ingestion (Python)            Processing                         Modeling (dbt + DuckDB)
───────                      ─────────────────             ──────────                         ───────────────────────
MOPS monthly revenue   ──►   mops_revenue_backfill   ─┐
Google News RSS (zh/en)──►   google_news             ─┼─►  filter_news  ──►  llm_extract  ─►  staging ─► intermediate ─► mart_layer_month
FRED commodity prices  ──►   fred_commodities        ─┘    (rules)          (gpt-oss-120b)                                      │
config/*.csv (companies, chain membership, queries, commodities) ──────────────────────────────────────►                        ▼
                                                                                                                       analysis/lead_lag.py
```

### Data
| Source | Coverage | Volume |
|---|---|---|
| MOPS monthly revenue (TWSE listed + TPEx OTC) | Jan 2021 – latest | ~123,000 company-months |
| Google News RSS, 45 queries in Chinese and English | Jan 2024 – latest, two-week windows | 114,202 headlines collected |
| FRED: copper, aluminum, tin, nickel, Brent, semiconductor PPI | Jan 2021 – latest | 6 monthly series |

The chain is modeled in five layers — upstream materials, chip manufacturing, AI server assembly and components, logistics, and end customers — covering 34 companies. Companies and their chain positions live in config files with a many-to-many membership table, so a second supply chain can be added without code changes.

### From 114,202 headlines to 17,253 LLM judgments
1. **Deduplication** across queries and syndicated copies → 98,278
2. **Entity matching:** a headline counts only if its *title* names a tracked company or topic (exact matching with exclusion lists, e.g. 陽明 the shipping line vs 陽明山 the mountain) → 69,905
3. **Market-noise filter:** stock-trading headlines (price targets, limit-up, institutional buying) removed → 56,219
4. **Sampling:** at most 10 headlines per company per two-week window; small companies are kept in full → 17,253
5. **LLM extraction:** 40 headlines per request; each returns relevance, one of 11 event types, direction and strength, validated with Pydantic

**LLM cost for all 17,253 headlines: about US$0.50.**

### Modeling choices
- **Leakage:** headlines that merely report already-published revenue or earnings are excluded from the signal; otherwise news would trivially "predict" the revenue it is quoting.
- **Look-ahead bias:** each month's signal is standardized against that layer's *past* months only, with at least 6 months of history required.
- **Positivity bias:** positive headlines outnumber negative ones about 17 to 1 for demand events, so the index measures deviation from a layer's own history rather than raw tone.
- **Data tests:** uniqueness, accepted values, and referential integrity between news, companies and chain membership run on every build.

## Limitations
- Signals use **headlines only**, not full articles (copyright and cost). A field in the labeling sheet records whether reading the full article would change the label.
- Google News returns at most ~100 results per query; TSMC and NVIDIA are therefore sampled rather than fully covered.
- About 30 months of overlap between news and revenue is a small sample for time-series inference.
- Most companies serve several end markets (e.g. Foxconn's iPhone business), which adds noise to an AI-server signal.
- The end-customer layer has no revenue series yet (US filings not yet integrated). "-KY" companies are not covered.

## Running it

Requires Python 3.12. API keys go in `.env` (never committed): `GROQ_API_KEY` and/or `OPENROUTER_API_KEY`.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python ingestion/mops_revenue_backfill.py --start 2021-01
python ingestion/google_news.py --start 2024-01-01
python ingestion/fred_commodities.py

python processing/filter_news.py
python processing/llm_extract.py --provider openrouter-groq

cd transform && dbt build --profiles-dir . && cd ..
python analysis/lead_lag.py
```

All ingestion steps cache raw responses and can be interrupted and resumed. Recent periods are re-fetched on every run because revenue and news arrive late.

## Repository layout
```
config/        companies, chain membership, news queries, commodity list
ingestion/     revenue, news and commodity collectors
processing/    rule-based filter, LLM extraction, LLM evaluation, labeling tool
evaluation/    hand-labeled evaluation set and results
transform/     dbt project (staging → intermediate → marts)
analysis/      lead–lag analysis
```

## Roadmap
- Dashboard (Streamlit): weekly events, layer tone, and revenue, framed as monitoring
- Scheduled weekly runs on AWS (S3 + Lambda/EventBridge) or GitHub Actions
- US SEC filings for cloud capex, to give the end-customer layer hard data
- Re-test the lead–lag hypothesis on data collected after this analysis
