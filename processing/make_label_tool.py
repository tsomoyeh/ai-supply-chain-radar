"""把 evaluation/labels.csv 轉成一個用下拉選單填寫的本機網頁。

執行：python processing/make_label_tool.py
然後在瀏覽器打開 evaluation/label_tool.html。
- 每個欄位都是中文下拉選單；選「無關」時自動帶入 other、中性、強度 0
- 填寫進度自動存在瀏覽器裡，關掉再打開不會遺失
- 填完按「下載 labels.csv」，再把下載的檔案移回 evaluation/ 取代原檔
"""
import json
from pathlib import Path

import pandas as pd

LABELS_PATH = Path("evaluation/labels.csv")
OUT_PATH = Path("evaluation/label_tool.html")

TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新聞標註</title>
<style>
  :root {
    --ink: #1c2633; --muted: #5d6878; --line: #dde2e8; --bg: #ffffff; --soft: #f4f6f8;
    --done: #0f766e; --done-bg: #e8f5f3; --todo: #a15c07;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif;
         color: var(--ink); background: var(--soft); font-size: 15px; line-height: 1.5; }
  header { position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--line);
           display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: center; padding: 12px 24px; }
  h1 { font-size: 17px; margin: 0; font-weight: 600; }
  .progress { color: var(--muted); }
  .progress b { color: var(--ink); }
  .bar { flex: 1 1 160px; height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; min-width: 120px; }
  .bar > div { height: 100%; background: var(--done); width: 0; transition: width .2s; }
  label.toggle { color: var(--muted); display: flex; gap: 6px; align-items: center; cursor: pointer; white-space: nowrap; }
  button { font: inherit; padding: 7px 14px; border-radius: 6px; border: 1px solid var(--ink);
           background: var(--ink); color: #fff; cursor: pointer; }
  button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--done); outline-offset: 2px; }
  main { max-width: 1100px; margin: 0 auto; padding: 16px 24px 80px; }
  .rule { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
  .item { background: var(--bg); border: 1px solid var(--line); border-left: 4px solid var(--todo);
          border-radius: 6px; padding: 12px 16px; margin-bottom: 10px; }
  .item.done { border-left-color: var(--done); }
  .item.done .num { color: var(--done); }
  .head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 8px; }
  .num { color: var(--todo); font-variant-numeric: tabular-nums; min-width: 2.2em; font-weight: 600; }
  .title { font-size: 16px; font-weight: 500; flex: 1; }
  .meta { color: var(--muted); font-size: 12px; white-space: nowrap; }
  .meta a { color: var(--muted); }
  .fields { display: grid; grid-template-columns: 110px minmax(220px, 1.6fr) 120px 140px 130px minmax(140px, 1fr);
            gap: 8px; padding-left: calc(2.2em + 10px); }
  .fields label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
  select, input { font: inherit; font-size: 14px; padding: 5px 6px; border: 1px solid var(--line);
                  border-radius: 5px; background: var(--bg); color: var(--ink); width: 100%; }
  select.empty { color: var(--todo); border-color: #e7c99c; }
  .item.hidden { display: none; }
  @media (max-width: 860px) { .fields { grid-template-columns: 1fr 1fr; padding-left: 0; } }
</style>
</head>
<body>
<header>
  <h1>新聞標註</h1>
  <span class="progress">已完成 <b id="done">0</b> / <span id="total">0</span></span>
  <div class="bar"><div id="fill"></div></div>
  <label class="toggle"><input type="checkbox" id="onlyTodo"> 只顯示未完成</label>
  <button id="download">下載 labels.csv</button>
</header>
<main>
  <p class="rule">只看標題判斷。選「無關」會自動帶入：其他、中性、強度 0。已公布的數字選「財報／營收公布」；對未來的預估選需求增加或下修。進度會自動存在這個瀏覽器裡。</p>
  <div id="list"></div>
</main>
<script>
const DATA = __DATA__;
const HEADER = __HEADER__;
const OPTIONS = {
  rel: [["", "請選擇"], ["1", "相關"], ["0", "無關"]],
  ev: [["", "請選擇"],
       ["demand_up", "需求增加、新訂單、樂觀展望"],
       ["demand_down", "需求下修、砍單、悲觀展望"],
       ["capacity_expansion", "擴產、新廠、資本支出、購地"],
       ["capacity_tight", "產能吃緊、缺貨、供不應求"],
       ["price_up", "漲價"],
       ["price_down", "降價"],
       ["supply_disruption", "停工、地震、斷料"],
       ["policy_trade", "關稅、出口管制、補貼"],
       ["financial_report", "財報／營收公布（已發生的數字）"],
       ["product_tech", "新產品、新技術"],
       ["other", "其他"]],
  dir: [["", "請選擇"], ["1", "正面 +1"], ["0", "中性 0"], ["-1", "負面 −1"]],
  str: [["", "請選擇"], ["0", "0 無關"], ["1", "1 小事"], ["2", "2 值得注意"], ["3", "3 重大"]],
  full_text_changes: [["", "沒讀原文"], ["N", "不會改變"], ["Y", "會改變"]],
};
const NAMES = { rel: "相關性", ev: "事件類型", dir: "方向", str: "強度", full_text_changes: "讀全文後", note: "備註" };
const KEY = "labelTool:" + DATA.length + ":" + DATA[0].article_id;

let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { saved = {}; }
for (const row of DATA) {
  const s = saved[row.article_id];
  // 只用瀏覽器裡「有填值」的欄位覆蓋，避免空白蓋掉 CSV 裡的預標
  if (s) for (const k in s) if (s[k] !== "" && s[k] != null) row[k] = s[k];
}

function persist() {
  const out = {};
  for (const r of DATA) {
    out[r.article_id] = { rel: r.rel, ev: r.ev, dir: r.dir, str: r.str,
                          full_text_changes: r.full_text_changes, note: r.note };
  }
  try { localStorage.setItem(KEY, JSON.stringify(out)); } catch (e) {}
}

function isDone(r) {
  if (r.rel === "0") return true;
  return r.rel === "1" && r.ev !== "" && r.dir !== "" && r.str !== "";
}

function makeSelect(row, field, item) {
  const sel = document.createElement("select");
  for (const [value, text] of OPTIONS[field]) {
    const o = document.createElement("option");
    o.value = value; o.textContent = text;
    sel.appendChild(o);
  }
  sel.value = row[field] || "";
  sel.classList.toggle("empty", field !== "full_text_changes" && sel.value === "");
  sel.addEventListener("change", () => {
    row[field] = sel.value;
    if (field === "rel" && sel.value === "0") {
      row.ev = "other"; row.dir = "0"; row.str = "0";
      for (const f of ["ev", "dir", "str"]) {
        const s = item.querySelector(`select[data-field="${f}"]`);
        s.value = row[f]; s.classList.remove("empty");
      }
    }
    sel.classList.toggle("empty", field !== "full_text_changes" && sel.value === "");
    update(item, row);
  });
  sel.dataset.field = field;
  return sel;
}

function update(item, row) {
  item.classList.toggle("done", isDone(row));
  persist();
  refresh();
}

function render() {
  const list = document.getElementById("list");
  DATA.forEach((row, i) => {
    const item = document.createElement("section");
    item.className = "item";
    const head = document.createElement("div");
    head.className = "head";
    const num = document.createElement("span");
    num.className = "num"; num.textContent = i + 1;
    const title = document.createElement("span");
    title.className = "title"; title.textContent = row.title;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${row.lang === "zh" ? "中文" : "英文"}　${row.date}　`;
    const a = document.createElement("a");
    a.href = row.link; a.target = "_blank"; a.rel = "noopener"; a.textContent = "原文";
    meta.appendChild(a);
    head.append(num, title, meta);

    const fields = document.createElement("div");
    fields.className = "fields";
    for (const f of ["rel", "ev", "dir", "str", "full_text_changes"]) {
      const lab = document.createElement("label");
      lab.append(NAMES[f], makeSelect(row, f, item));
      fields.appendChild(lab);
    }
    const lab = document.createElement("label");
    const note = document.createElement("input");
    note.value = row.note || ""; note.placeholder = "拿不定時寫原因";
    note.addEventListener("input", () => { row.note = note.value; persist(); });
    lab.append(NAMES.note, note);
    fields.appendChild(lab);

    item.append(head, fields);
    item.classList.toggle("done", isDone(row));
    list.appendChild(item);
  });
}

function refresh() {
  const done = DATA.filter(isDone).length;
  document.getElementById("done").textContent = done;
  document.getElementById("total").textContent = DATA.length;
  document.getElementById("fill").style.width = (100 * done / DATA.length) + "%";
}

document.getElementById("onlyTodo").addEventListener("change", (e) => {
  document.querySelectorAll(".item").forEach((item, i) => {
    item.classList.toggle("hidden", e.target.checked && isDone(DATA[i]));
  });
});

document.getElementById("download").addEventListener("click", () => {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [HEADER.join(",")].concat(DATA.map((r) => HEADER.map((h) => esc(r[h])).join(",")));
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "labels.csv";
  a.click();
  URL.revokeObjectURL(a.href);
});

render();
refresh();
</script>
</body>
</html>
"""


def main() -> None:
    df = pd.read_csv(LABELS_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    header = list(df.columns)
    data = json.dumps(df.to_dict("records"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data).replace("__HEADER__", json.dumps(header))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"已產生 {OUT_PATH}（{len(df)} 則），用瀏覽器打開即可開始標註")


if __name__ == "__main__":
    main()
