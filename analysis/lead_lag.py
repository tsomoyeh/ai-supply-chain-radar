"""領先落後分析：新聞訊號能不能比營收更早反映景氣變化？

執行（在專案根目錄）：python analysis/lead_lag.py

做法：
- 對每一層、每種訊號，把訊號往前錯開 k 個月，跟營收算相關係數
  k > 0 代表「新聞領先營收 k 個月」，k < 0 代表「營收領先新聞」
- 兩種比法：
  水準：訊號 vs 營收年增率（兩者都有長期趨勢，相關性容易被高估）
  變化：訊號的月變化 vs 年增率的月變化（去掉趨勢，比較能看出真正的領先關係）
- 用 Spearman 等級相關，不容易被極端值影響
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DB_PATH = Path("data/warehouse.duckdb")
OUT_DIR = Path("analysis/output")
LAGS = range(-3, 7)
SIGNALS = {
    "score_3m": "語氣分數",
    "signal_index": "標準化指數",
    "n_articles": "新聞數量",
    "pos_share": "正面比例",
}
LAYERS_WITH_REVENUE = ["1_upstream", "2_manufacturing", "3_ai_server", "4_logistics"]


def spearman(x: pd.Series, y: pd.Series) -> tuple:
    ok = x.notna() & y.notna()
    n = int(ok.sum())
    if n < 8 or x[ok].nunique() < 2 or y[ok].nunique() < 2:
        return np.nan, n
    return float(np.corrcoef(x[ok].rank(), y[ok].rank())[0, 1]), n


def load() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.sql("""
        select layer, month, n_articles, n_positive, n_negative, score_3m, signal_index, revenue_yoy_pct
        from mart_layer_month
        where is_complete_month and month >= date '2024-01-01'
        order by layer, month
    """).df()
    con.close()
    df["pos_share"] = df["n_positive"] / (df["n_positive"] + df["n_negative"])
    return df


def analyze(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer in LAYERS_WITH_REVENUE:
        d = df[df["layer"] == layer].sort_values("month").set_index("month")
        target = {"水準": d["revenue_yoy_pct"], "變化": d["revenue_yoy_pct"].diff()}
        for col, name in SIGNALS.items():
            signal = {"水準": d[col], "變化": d[col].diff()}
            for mode in ["水準", "變化"]:
                for k in LAGS:
                    # 訊號往後移 k 個月：今天的營收對照 k 個月前的訊號
                    r, n = spearman(signal[mode].shift(k), target[mode])
                    rows.append({"layer": layer, "signal": name, "mode": mode, "lag": k, "r": r, "n": n})
    return pd.DataFrame(rows)


def main() -> None:
    df = load()
    res = analyze(df)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT_DIR / "lead_lag_results.csv", index=False, encoding="utf-8-sig")

    n = int(res["n"].median())
    threshold = 2 / np.sqrt(n)
    print(f"每個組合約 {n} 個月的資料；|r| 大於約 {threshold:.2f} 才算比較明顯的相關")
    print("（月資料前後相關性高，這個門檻只是粗略參考，實際上需要更大的 |r| 才可信）\n")

    pd.set_option("display.width", 200)
    for layer in LAYERS_WITH_REVENUE:
        sub = res[res["layer"] == layer]
        table = sub.pivot_table(index=["mode", "signal"], columns="lag", values="r").round(2)
        table.columns = [f"{c:+d}" for c in table.columns]
        print(f"=== {layer}（欄位是領先月數：正數 = 新聞領先營收）===")
        print(table.to_string())
        print()

    lead = res[(res["mode"] == "變化") & (res["lag"] >= 1)].dropna(subset=["r"])
    top = lead.reindex(lead["r"].abs().sort_values(ascending=False).index).head(8)
    print("=== 去掉趨勢後，新聞「領先」營收最強的組合 ===")
    print(top[["layer", "signal", "lag", "r", "n"]].round(2).to_string(index=False))
    total = res["r"].notna().sum()
    print(f"\n注意：總共比較了 {total} 個組合，就算完全沒有關係，也會有幾個組合碰巧出現 |r| 0.4 以上。"
          "\n可信的領先關係應該同時滿足：相鄰月數也有同方向的相關、多種訊號定義結果一致、而且說得出產業上的道理。")
    print(f"\n完整結果已存到 {OUT_DIR / 'lead_lag_results.csv'}")


if __name__ == "__main__":
    main()
