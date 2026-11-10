"""AI 供應鏈雷達儀表板（中英切換）。

本機執行（在專案根目錄）：streamlit run dashboard/app.py
資料來自 dashboard/snapshot/，由 dashboard/export_data.py 產生。
"""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

SNAPSHOT = Path(__file__).parent / "snapshot"

# ---------- 中英對照 ----------
T = {
    "zh": {
        "title": "AI 供應鏈雷達",
        "subtitle": "追蹤半導體與 AI 伺服器供應鏈：從原物料到雲端客戶的即時新聞監測",
        "lang": "語言",
        "data_note": "新聞期間 {start} ～ {end}　｜　資料更新於 {gen}",
        "tab_week": "近期動態", "tab_overview": "供應鏈總覽", "tab_layer": "層級深入", "tab_research": "研究方法與結果",
        "week_header": "最近 {days} 天的供應鏈事件",
        "week_caption": "月營收要到下個月 10 號才公布；新聞讓你提早看到供應鏈正在發生的事。",
        "days": "期間（天）", "filter_layer": "層級", "filter_event": "事件類型", "filter_dir": "方向",
        "dir_all": "全部", "dir_pos": "正面", "dir_neg": "負面",
        "hide_reported": "隱藏財報／營收公布",
        "n_events": "事件數", "n_pos": "正面", "n_neg": "負面",
        "no_events": "這個條件下沒有事件。",
        "show_top": "依強度排序，顯示前 {n} 則",
        "overview_header": "各層最新狀態（{month}）",
        "overview_caption": "語氣分數：近 3 個月新聞的平均方向 × 強度；變化是跟上個月相比。營收年增率是同層公司營收加總後計算。",
        "tone": "新聞語氣", "rev_yoy": "營收年增率", "n_news": "新聞數", "no_rev": "尚無營收資料",
        "index_label": "相對過去：{v:+.1f} 個標準差",
        "layer_select": "選擇層級",
        "chart_title": "新聞語氣與營收年增率",
        "tone_axis": "新聞語氣（3 個月平均）", "rev_axis": "營收年增率 (%)", "news_axis": "每月新聞數",
        "companies_header": "這一層的公司（近 3 個月）",
        "col_company": "公司", "col_segment": "細分產業", "col_news": "新聞數", "col_tone": "平均語氣", "col_rev": "最新營收年增率 (%)",
        "recent_header": "這一層最近的重要事件",
        "research_header": "研究問題：新聞能不能比月營收更早反映景氣？",
        "research_answer": "**結論：目前不能。** 依照事先訂好的標準（去掉趨勢後，新聞領先 1～3 個月、相關係數 ≥ 0.4、相鄰月份方向一致、至少兩種訊號定義相符），四個有營收資料的層級都沒有通過。新聞語氣大致是跟著景氣走，而不是走在前面，所以這個工具定位為即時監測，而非預測。",
        "eval_header": "LLM 判斷準確率（100 則人工標註新聞）",
        "eval_caption": "事件類型與方向只計算人工標為相關的新聞。同一個開源模型交給不同服務商執行，準確率可以差到 17 個百分點。",
        "col_system": "系統", "col_rel": "相關性", "col_event": "事件類型", "col_dir": "方向",
        "leadlag_header": "領先落後分析（去掉趨勢後）",
        "leadlag_caption": "橫軸是領先月數：正數代表新聞領先營收。顏色越深代表相關越強；總共比較 320 個組合，碰巧出現 0.4 左右的數字是正常的。",
        "lag_axis": "新聞領先營收的月數", "signal_axis": "訊號定義", "r_axis": "相關係數",
        "repo": "原始碼與完整說明：",
    },
    "en": {
        "title": "AI Supply Chain Radar",
        "subtitle": "Near-real-time news monitoring of the semiconductor and AI server supply chain, from raw materials to cloud customers",
        "lang": "Language",
        "data_note": "News from {start} to {end}  |  Data updated {gen}",
        "tab_week": "Recent events", "tab_overview": "Overview", "tab_layer": "Layer detail", "tab_research": "Method & results",
        "week_header": "Supply chain events in the last {days} days",
        "week_caption": "Monthly revenue is published around the 10th of the following month; news shows what is happening now.",
        "days": "Period (days)", "filter_layer": "Layer", "filter_event": "Event type", "filter_dir": "Direction",
        "dir_all": "All", "dir_pos": "Positive", "dir_neg": "Negative",
        "hide_reported": "Hide reported results",
        "n_events": "Events", "n_pos": "Positive", "n_neg": "Negative",
        "no_events": "No events match these filters.",
        "show_top": "Sorted by strength, showing the top {n}",
        "overview_header": "Latest status by layer ({month})",
        "overview_caption": "Tone: average direction × strength of news over the last 3 months; change vs the previous month. Revenue growth is computed on the layer's combined revenue.",
        "tone": "News tone", "rev_yoy": "Revenue YoY", "n_news": "Articles", "no_rev": "No revenue data yet",
        "index_label": "Vs own history: {v:+.1f} std dev",
        "layer_select": "Choose a layer",
        "chart_title": "News tone vs revenue growth",
        "tone_axis": "News tone (3-month avg)", "rev_axis": "Revenue YoY (%)", "news_axis": "Articles per month",
        "companies_header": "Companies in this layer (last 3 months)",
        "col_company": "Company", "col_segment": "Segment", "col_news": "Articles", "col_tone": "Avg tone", "col_rev": "Latest revenue YoY (%)",
        "recent_header": "Recent notable events in this layer",
        "research_header": "Research question: does news lead monthly revenue?",
        "research_answer": "**Answer: not so far.** Under criteria fixed in advance (after removing trends, a 1–3 month lead with |r| ≥ 0.4, the same direction at neighboring lags, and agreement between at least two signal definitions), none of the four layers with revenue data passed. News tone mostly moves with the cycle rather than ahead of it, so this tool is positioned for monitoring, not forecasting.",
        "eval_header": "LLM accuracy (100 hand-labeled headlines)",
        "eval_caption": "Event type and direction are measured on headlines labeled as relevant. The same open-weight model lost up to 17 points when served by a different provider.",
        "col_system": "System", "col_rel": "Relevance", "col_event": "Event type", "col_dir": "Direction",
        "leadlag_header": "Lead–lag analysis (trend removed)",
        "leadlag_caption": "X axis: months the news leads revenue (positive = news first). Darker means stronger correlation; with 320 comparisons, values around 0.4 appear by chance.",
        "lag_axis": "Months news leads revenue", "signal_axis": "Signal definition", "r_axis": "Correlation",
        "repo": "Source code and full write-up:",
    },
}

LAYERS = {
    "0_macro": {"zh": "政策與總體", "en": "Policy & macro"},
    "1_upstream": {"zh": "上游原物料", "en": "Upstream materials"},
    "2_manufacturing": {"zh": "晶片製造", "en": "Chip manufacturing"},
    "3_ai_server": {"zh": "AI 伺服器", "en": "AI servers"},
    "4_logistics": {"zh": "物流", "en": "Logistics"},
    "5_end_customer": {"zh": "終端客戶", "en": "End customers"},
}
EVENTS = {
    "demand_up": {"zh": "需求增加", "en": "Demand up"},
    "demand_down": {"zh": "需求下修", "en": "Demand down"},
    "capacity_expansion": {"zh": "擴產", "en": "Capacity expansion"},
    "capacity_tight": {"zh": "產能吃緊", "en": "Capacity tight"},
    "price_up": {"zh": "漲價", "en": "Price up"},
    "price_down": {"zh": "降價", "en": "Price down"},
    "supply_disruption": {"zh": "供應中斷", "en": "Supply disruption"},
    "policy_trade": {"zh": "政策貿易", "en": "Policy & trade"},
    "financial_report": {"zh": "財報公布", "en": "Reported results"},
    "product_tech": {"zh": "新產品技術", "en": "Product & tech"},
    "other": {"zh": "其他", "en": "Other"},
}
SIGNALS = {"語氣分數": "Tone", "標準化指數": "Standardized index", "新聞數量": "Volume", "正面比例": "Positive share"}
SYSTEMS = {
    "關鍵字規則": {"zh": "關鍵字規則（基準）", "en": "Keyword rules (baseline)"},
    "openai_gpt-oss-120b": {"zh": "gpt-oss-120b · Groq", "en": "gpt-oss-120b · Groq"},
    "openrouter-groq_openai_gpt-oss-120b": {"zh": "gpt-oss-120b · OpenRouter → Groq", "en": "gpt-oss-120b · OpenRouter → Groq"},
    "openrouter_openai_gpt-oss-120b": {"zh": "gpt-oss-120b · OpenRouter → DeepInfra", "en": "gpt-oss-120b · OpenRouter → DeepInfra"},
    "qwen_qwen3.8-27b": {"zh": "qwen3.8-27b · Groq", "en": "qwen3.8-27b · Groq"},
}
REPO_URL = "https://github.com/tsomoyeh/ai-supply-chain-radar"


@st.cache_data
def load():
    data = {name: pd.read_parquet(SNAPSHOT / f"{name}.parquet")
            for name in ["layer_month", "events", "company_month", "lead_lag", "llm_eval"]}
    data["meta"] = json.loads((SNAPSHOT / "meta.json").read_text(encoding="utf-8"))
    return data


def layer_name(code, lang):
    return LAYERS.get(code, {}).get(lang, code)


def event_name(code, lang):
    return EVENTS.get(code, {}).get(lang, code)


def render_events(df, lang, limit):
    arrow = {1: "▲", -1: "▼", 0: "●"}
    lines = []
    for r in df.head(limit).itertuples():
        companies = r.companies_zh if lang == "zh" else r.companies_en
        meta = " · ".join(x for x in [
            r.published_at.strftime("%Y-%m-%d"), r.source, companies if isinstance(companies, str) else "",
            f"{event_name(r.event_type, lang)} {arrow.get(r.direction, '')}{'★' * int(r.strength)}",
        ] if x)
        title = r.title.replace("[", "［").replace("]", "］")
        lines.append(f"- [{title}]({r.link})  \n  <small>{meta}</small>")
    st.markdown("\n".join(lines), unsafe_allow_html=True)


def tab_recent(d, t, lang):
    events = d["events"].copy()
    end = events["published_at"].max()
    c1, c2, c3, c4 = st.columns([1, 2, 2, 1.4])
    days = c1.selectbox(t["days"], [7, 14, 30, 90], index=1)
    layer_opts = [k for k in LAYERS if events["layers"].fillna("").str.contains(k).any()]
    layers = c2.multiselect(t["filter_layer"], layer_opts, format_func=lambda k: layer_name(k, lang))
    ev_types = c3.multiselect(t["filter_event"], list(EVENTS), format_func=lambda k: event_name(k, lang))
    direction = c4.radio(t["filter_dir"], ["all", "pos", "neg"], horizontal=True,
                         format_func=lambda k: t[f"dir_{k}"])
    hide_reported = st.checkbox(t["hide_reported"], value=True)

    e = events[events["published_at"] > end - pd.Timedelta(days=days)]
    if layers:
        e = e[e["layers"].fillna("").apply(lambda s: any(l in s.split("|") for l in layers))]
    if ev_types:
        e = e[e["event_type"].isin(ev_types)]
    if direction != "all":
        e = e[e["direction"] == (1 if direction == "pos" else -1)]
    if hide_reported:
        e = e[~e["is_reported_result"]]

    st.subheader(t["week_header"].format(days=days))
    st.caption(t["week_caption"])
    m1, m2, m3 = st.columns(3)
    m1.metric(t["n_events"], len(e))
    m2.metric(t["n_pos"], int((e["direction"] > 0).sum()))
    m3.metric(t["n_neg"], int((e["direction"] < 0).sum()))
    if e.empty:
        st.info(t["no_events"])
        return
    e = e.sort_values(["strength", "published_at"], ascending=False)
    st.caption(t["show_top"].format(n=min(60, len(e))))
    render_events(e, lang, 60)


def tab_overview(d, t, lang):
    lm = d["layer_month"]
    complete = lm[lm["is_complete_month"] & lm["score_3m"].notna()]
    latest = complete["month"].max()
    st.subheader(t["overview_header"].format(month=latest.strftime("%Y-%m")))
    st.caption(t["overview_caption"])
    codes = list(LAYERS)
    for i, code in enumerate(codes):
        if i % 3 == 0:
            cols = st.columns(3)  # 每三張卡片一列，高度才會對齊
        s = lm[lm["layer"] == code].sort_values("month")
        now = s[s["month"] == latest]
        prev = s[s["month"] == latest - pd.DateOffset(months=1)]
        with cols[i % 3].container(border=True):
            st.markdown(f"**{layer_name(code, lang)}**")
            if now.empty:
                st.caption("—")
                continue
            now, prev = now.iloc[0], (prev.iloc[0] if not prev.empty else None)
            tone_delta = None if prev is None or pd.isna(prev["score_3m"]) else round(now["score_3m"] - prev["score_3m"], 2)
            st.metric(t["tone"], f"{now['score_3m']:.2f}", tone_delta)
            if pd.notna(now["signal_index"]):
                st.caption(t["index_label"].format(v=now["signal_index"]))
            rev = s[s["revenue_yoy_pct"].notna()]
            if rev.empty:
                st.caption(t["no_rev"])
            else:
                last = rev.iloc[-1]
                prev_rev = rev.iloc[-2]["revenue_yoy_pct"] if len(rev) > 1 else None
                delta = None if prev_rev is None else f"{last['revenue_yoy_pct'] - prev_rev:+.1f} pt"
                st.metric(f"{t['rev_yoy']} ({last['month'].strftime('%Y-%m')})", f"{last['revenue_yoy_pct']:.1f}%", delta)
            st.caption(f"{t['n_news']}: {int(now['n_articles']) if pd.notna(now['n_articles']) else 0}")


def tab_layer(d, t, lang):
    lm = d["layer_month"]
    code = st.selectbox(t["layer_select"], list(LAYERS), index=3, format_func=lambda k: layer_name(k, lang))
    s = lm[(lm["layer"] == code) & lm["is_complete_month"] & (lm["month"] >= "2024-01-01")].sort_values("month")

    st.subheader(t["chart_title"])
    base = alt.Chart(s).encode(x=alt.X("month:T", title=None))
    tone = base.mark_line(point=True, color="#7b7bf0").encode(
        y=alt.Y("score_3m:Q", title=t["tone_axis"], axis=alt.Axis(titleColor="#7b7bf0")), tooltip=["month:T", alt.Tooltip("score_3m:Q", format=".2f")])
    layers = [tone]
    if s["revenue_yoy_pct"].notna().any():
        rev = base.mark_line(strokeDash=[5, 3], color="#14b8a6").encode(
            y=alt.Y("revenue_yoy_pct:Q", title=t["rev_axis"], axis=alt.Axis(titleColor="#14b8a6")),
            tooltip=["month:T", alt.Tooltip("revenue_yoy_pct:Q", format=".1f")])
        layers.append(rev)
    st.altair_chart(alt.layer(*layers).resolve_scale(y="independent").properties(height=320), width="stretch")
    bars = base.mark_bar(color="#c7cbd1").encode(y=alt.Y("n_articles:Q", title=t["news_axis"])).properties(height=140)
    st.altair_chart(bars, width="stretch")

    cm = d["company_month"]
    cm = cm[cm["layer"] == code]
    if not cm.empty:
        st.subheader(t["companies_header"])
        recent_months = sorted(cm["month"].unique())[-4:-1]  # 最近 3 個完整月份
        recent = cm[cm["month"].isin(recent_months)]
        agg = recent.groupby(["stock_id", "name_zh", "name_en", "segment"], dropna=False).agg(
            news=("n_articles", "sum"), tone=("avg_score", "mean")).reset_index()
        last_rev = cm.dropna(subset=["revenue_yoy_pct"]).sort_values("month").groupby("stock_id")["revenue_yoy_pct"].last()
        agg["rev"] = agg["stock_id"].map(last_rev)
        agg["company"] = agg["name_zh"] if lang == "zh" else agg["name_en"]
        table = agg[["company", "segment", "news", "tone", "rev"]].sort_values("news", ascending=False)
        table.columns = [t["col_company"], t["col_segment"], t["col_news"], t["col_tone"], t["col_rev"]]
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={t["col_tone"]: st.column_config.NumberColumn(format="%.2f"),
                                    t["col_rev"]: st.column_config.NumberColumn(format="%.1f"),
                                    t["col_news"]: st.column_config.NumberColumn(format="%d")})

    st.subheader(t["recent_header"])
    ev = d["events"]
    ev = ev[ev["layers"].fillna("").str.split("|").apply(lambda xs: code in xs) & ~ev["is_reported_result"]]
    ev = ev[ev["published_at"] > ev["published_at"].max() - pd.Timedelta(days=30)]
    render_events(ev.sort_values(["strength", "published_at"], ascending=False), lang, 15)


def tab_research(d, t, lang):
    st.subheader(t["research_header"])
    st.markdown(t["research_answer"])

    st.subheader(t["eval_header"])
    st.caption(t["eval_caption"])
    ev = d["llm_eval"].copy()
    ev["system"] = ev["system"].map(lambda s: SYSTEMS.get(s, {}).get(lang, s))
    ev = ev.sort_values("event_type", ascending=False)[["system", "relevance", "event_type", "direction"]]
    for c in ["relevance", "event_type", "direction"]:
        ev[c] = (ev[c] * 100).round(0)
    ev.columns = [t["col_system"], t["col_rel"], t["col_event"], t["col_dir"]]
    st.dataframe(ev, hide_index=True, width="stretch",
                 column_config={c: st.column_config.ProgressColumn(c, format="%d%%", min_value=0, max_value=100)
                                for c in ev.columns[1:]})

    st.subheader(t["leadlag_header"])
    st.caption(t["leadlag_caption"])
    ll = d["lead_lag"]
    ll = ll[ll["mode"] == "變化"].copy()
    ll["layer_name"] = ll["layer"].map(lambda k: layer_name(k, lang))
    if lang == "en":
        ll["signal"] = ll["signal"].map(SIGNALS)
    heat = alt.Chart(ll).mark_rect().encode(
        x=alt.X("lag:O", title=t["lag_axis"]),
        y=alt.Y("signal:N", title=t["signal_axis"]),
        color=alt.Color("r:Q", title=t["r_axis"], scale=alt.Scale(scheme="redblue", domain=[-0.8, 0.8])),
        tooltip=["layer_name", "signal", "lag", alt.Tooltip("r:Q", format=".2f")],
    ).properties(width=340, height=120).facet(facet=alt.Facet("layer_name:N", title=None), columns=2)
    st.altair_chart(heat)

    st.markdown(f"{t['repo']} [{REPO_URL}]({REPO_URL})")


def main():
    st.set_page_config(page_title="AI Supply Chain Radar", page_icon="📡", layout="wide")
    lang = st.sidebar.radio("語言 / Language", ["zh", "en"], format_func=lambda k: "中文" if k == "zh" else "English")
    t = T[lang]
    d = load()
    st.title(t["title"])
    st.caption(t["subtitle"])
    st.sidebar.caption(t["data_note"].format(start=d["meta"]["news_from"], end=d["meta"]["news_to"],
                                             gen=d["meta"]["generated_at"]))
    tabs = st.tabs([t["tab_week"], t["tab_overview"], t["tab_layer"], t["tab_research"]])
    with tabs[0]:
        tab_recent(d, t, lang)
    with tabs[1]:
        tab_overview(d, t, lang)
    with tabs[2]:
        tab_layer(d, t, lang)
    with tabs[3]:
        tab_research(d, t, lang)


main()
