import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import dp_core as dp
import ui

model, flt, skus = ui.ctx()
fc_skus = set(model.fc["sku"]) & skus
fcm = model.fc_months
ui.header("Forecast vs Actual",
          f"เทียบยอดขายจริง (บิล NV/IV) กับ Forecast · หน่วย: จำนวน · "
          f"{len(fc_skus):,} SKU ที่มี forecast · {ui.fmt_month(fcm[0]) if fcm else '-'} – "
          f"{ui.fmt_month(fcm[-1]) if fcm else '-'}")

acc_all = dp.accuracy_frame(model)
acc_all = acc_all[acc_all["sku"].isin(fc_skus)]
months = sorted(acc_all["month"].unique().tolist())
if not months:
    st.info("ยังไม่มีเดือนที่มีทั้ง Forecast และยอดขายจริง")
    st.stop()

sel = st.multiselect("เดือนที่ประเมิน", months, default=[months[-1]], format_func=dp.month_label)
if not sel:
    st.info("เลือกอย่างน้อย 1 เดือน")
    st.stop()
if model.last_month in sel and not model.last_month_complete:
    st.warning(f"{dp.month_label(model.last_month)} ยังไม่ครบเดือน — ยอดจริงจะต่ำกว่าความเป็นจริง")

acc = acc_all[acc_all["month"].isin(sel)]
s = dp.summarize(acc).iloc[0]

# เทียบเดือนก่อนหน้า (ถ้ามี)
prev_m = [m for m in months if m < min(sel)]
ps = dp.summarize(acc_all[acc_all["month"] == prev_m[-1]]).iloc[0] if prev_m else None
pv = (lambda k, f=ui.fmt_pct: f" · เดือนก่อน {f(ps[k])}" if ps is not None else "")

tab1, tab5, tab2, tab3, tab4 = st.tabs(["ภาพรวม", "⚠️ เฝ้าระวังของขาด", "แยกกลุ่ม", "ราย SKU", "ยังไม่มี Forecast"])

# ============================================================ ภาพรวม
with tab1:
    ui.section("ภาพรวมเดือนที่เลือก")
    c = st.columns(5)
    ui.kpi(c[0], "Forecast Accuracy", ui.fmt_pct(s["accuracy"]), "1 − WAPE" + pv("accuracy"), ui.BLUE, "🎯")
    ui.kpi(c[1], "MAE", ui.fmt_num(s["mae"], 1),
           "หน่วย/SKU/เดือน" + pv("mae", lambda v: ui.fmt_num(v, 1)) + f" · RMSE {ui.fmt_num(s['rmse'], 0)}",
           ui.RED, "📏")
    ui.kpi(c[2], "Bias", ui.fmt_pct(s["bias"], sign=True),
           ("พยากรณ์เกิน" if s["bias"] > 0 else "พยากรณ์ขาด") + pv("bias", lambda v: ui.fmt_pct(v, sign=True)),
           ui.ORANGE, "⚖️")
    ui.kpi(c[3], "SKU แม่น ≥ 80%", ui.fmt_pct(s["sku_hit_rate"], 0),
           f"{int(round(s['sku_hit_rate'] * s['n_sku'])):,} จาก {int(s['n_sku']):,} SKU", ui.TEAL, "✅")
    ui.kpi(c[4], "Forecast / Actual", f"{ui.fmt_num(s['forecast'])}",
           f"ยอดจริง {ui.fmt_num(s['actual'])} หน่วย", ui.PURPLE, "📦")

    # แนวโน้มรายเดือน: ยอดจริงของ SKU ที่มี forecast + forecast
    act = model.monthly[model.monthly["sku"].isin(fc_skus)].groupby("month")["qty"].sum()
    fsum = model.fc[model.fc["sku"].isin(fc_skus)].groupby("month")["forecast_qty"].sum()
    rng = dp.month_range(dp.month_add(model.last_month, -11), max([model.last_month] + fcm))
    tr = pd.DataFrame({"month": rng, "label": [dp.month_label(m) for m in rng]})
    tr["actual"] = [act.get(m, 0.0) if m <= model.last_month else np.nan for m in rng]
    tr["forecast"] = tr["month"].map(fsum)

    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        ui.card_title("ยอดจริง vs Forecast รายเดือน (หน่วย)")
        fig = go.Figure()
        fig.add_scatter(x=tr["label"], y=tr["actual"], name="ยอดจริง", mode="lines+markers",
                        line=dict(color=ui.BLUE, width=3), fill="tozeroy", fillcolor="rgba(56,189,248,.18)")
        fig.add_scatter(x=tr["label"], y=tr["forecast"], name="Forecast", mode="lines+markers",
                        line=dict(color=ui.ORANGE, width=3, dash="dot"))
        ui.avg_line(fig, tr["actual"].mean(), "เฉลี่ย 12 ด.", ui.TEAL)
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(ui.style(fig, 380), use_container_width=True)
        st.caption("ยอดจริงนับเฉพาะ SKU ที่อยู่ในชีต Forecast")
    with c2, st.container(border=True):
        ui.card_title("Accuracy แยกหมวด")
        bc = dp.summarize(acc, "category").dropna(subset=["accuracy"]).sort_values("category")
        bc["label"] = "หมวด " + bc["category"].map(lambda x: str(int(x)) if pd.notna(x) else "-")
        fig = go.Figure(go.Bar(x=bc["label"], y=bc["accuracy"], marker_color=ui.SERIES[:len(bc)],
                               text=[ui.fmt_pct(v, 0) for v in bc["accuracy"]], textposition="outside",
                               customdata=np.stack([bc["n_sku"], bc["bias"]], axis=1),
                               hovertemplate="%{x}<br>Accuracy %{y:.1%}<br>%{customdata[0]:.0f} SKU · "
                                             "Bias %{customdata[1]:+.0%}<extra></extra>"))
        ui.avg_line(fig, s["accuracy"], "รวม", ui.ORANGE, "{:.0%}")
        fig.update_yaxes(tickformat=".0%", range=[0, 1.1])
        st.plotly_chart(ui.style(fig, 380, legend=False), use_container_width=True)

    if len(months) > 1:
        with st.container(border=True):
            ui.card_title("Accuracy และ Bias รายเดือน")
            bm = dp.summarize(acc_all, "month")
            bm["label"] = bm["month"].map(dp.month_label)
            fig = go.Figure()
            fig.add_scatter(x=bm["label"], y=bm["accuracy"], name="Accuracy", mode="lines+markers",
                            line=dict(color=ui.BLUE, width=3), fill="tozeroy", fillcolor="rgba(56,189,248,.15)")
            fig.add_scatter(x=bm["label"], y=bm["bias"], name="Bias", mode="lines+markers",
                            line=dict(color=ui.ORANGE, width=2))
            ui.avg_line(fig, bm["accuracy"].mean(), "เฉลี่ย", ui.ORANGE, "{:.1%}")
            fig.update_yaxes(tickformat=".0%")
            st.plotly_chart(ui.style(fig, 320), use_container_width=True)

# ============================================================ เฝ้าระวังของขาด
with tab5:
    groups = sorted(model.master["ABC_XYZ"].dropna().unique().tolist())
    cc1, cc2 = st.columns([3, 1])
    focus = cc1.multiselect("กลุ่มที่เฝ้าระวัง", groups,
                            default=[g for g in ["AX", "AY", "BX"] if g in groups], key="watch_groups")
    thr = cc2.select_slider("เกณฑ์ต่างเกิน", options=[0.1, 0.2, 0.3, 0.5], value=0.2,
                            format_func=lambda v: f"{v:.0%}", key="watch_thr")
    w = dp.stockout_watch(model, tuple(focus), thr)
    w = w[w["sku"].isin(skus)]
    risk = w[w["risk_score"] > 0]
    c = st.columns(4)
    ui.kpi(c[0], "SKU ที่เฝ้าระวัง", f"{len(risk):,}", f"จาก {len(w):,} SKU ในกลุ่มที่เลือก", ui.RED, "⚠️")
    ui.kpi(c[1], "ขายจริงเกิน FC", f"{risk['risk_flags'].str.contains('ขายจริงเกิน').sum():,}",
           f"เดือนล่าสุดที่ประเมิน · เกิน {thr:.0%}", ui.ORANGE, "📈")
    ui.kpi(c[2], "FC เดือนหน้าต่ำ", f"{risk['risk_flags'].str.contains('FC เดือนหน้าต่ำ').sum():,}",
           f"{w['next_month'].iloc[0] if len(w) else '-'} ต่ำกว่าเฉลี่ย 3 ด. เกิน {thr:.0%}", ui.PURPLE, "📉")
    ui.kpi(c[3], "ไม่มี FC เดือนหน้า", f"{risk['risk_flags'].str.contains('ไม่มี FC').sum():,}",
           "ควรเพิ่มในชีต Forecast", ui.BLUE, "❓")
    with st.container(border=True):
        ui.card_title("รายการที่ควรเน้น (เรียงตามจำนวนสัญญาณเสี่ยง และส่วนต่างที่อาจขาด)")
        cols = ["sku", "name", "ABC_XYZ", "priority_tier", "risk_score", "recent3", "act_last", "fc_last",
                "fc_next", "gap_next", "safety_stock", "reorder_point", "risk_flags"]
        st.dataframe(risk[cols], hide_index=True, use_container_width=True, height=460, column_config={
            **ui.SKU_COLS, "risk_score": st.column_config.ProgressColumn("ความเสี่ยง", format="%d / 3",
                                                                          min_value=0, max_value=3),
            "recent3": ui.num("เฉลี่ย 3 ด. ล่าสุด"), "act_last": ui.num("ขายจริงเดือนล่าสุด"),
            "fc_last": ui.num("FC เดือนล่าสุด"), "fc_next": ui.num("FC เดือนหน้า"),
            "gap_next": ui.num("อาจขาด (หน่วย)", help="เฉลี่ย 3 ด. ล่าสุด − FC เดือนหน้า"),
            "safety_stock": ui.num("SS"), "reorder_point": ui.num("ROP"), "risk_flags": "สัญญาณ"})
        st.download_button("⬇️ ดาวน์โหลดรายการเฝ้าระวัง (CSV)", risk[cols].to_csv(index=False).encode("utf-8-sig"),
                           file_name="stockout_watch.csv", mime="text/csv")
    st.caption("สัญญาณเสี่ยง: (1) ขายจริงเดือนล่าสุดเกิน FC · (2) FC เดือนหน้าต่ำกว่ายอดขายเฉลี่ย 3 เดือนล่าสุด หรือไม่มี FC · "
               "(3) ยอดขาย 3 เดือนล่าสุดสูงกว่าค่าเฉลี่ยในอดีต (ดีมานด์กำลังโต)")

# ============================================================ แยกกลุ่ม
with tab2:
    dim_map = {"หมวด": "category", "ABC": "ABC", "ABC-XYZ": "ABC_XYZ", "Priority tier": "priority_tier",
               "XYZ": "XYZ", "Production": "Production"}
    dim_lbl = st.radio("มุมมอง", list(dim_map), horizontal=True)
    dim = dim_map[dim_lbl]
    bd = dp.summarize(acc, dim).sort_values("actual", ascending=False)
    bd[dim] = bd[dim].map(lambda x: str(int(x)) if isinstance(x, float) and pd.notna(x) else str(x))
    c1, c2 = st.columns([3, 2])
    with c1, st.container(border=True):
        ui.card_title(f"สรุปตาม {dim_lbl}")
        show = bd.copy()
        for k in ["wape", "accuracy", "bias", "sku_hit_rate"]:
            show[k] = show[k] * 100
        st.dataframe(show, hide_index=True, use_container_width=True, column_config={
            dim: dim_lbl, "n_sku": ui.num("SKU"), "actual": ui.num("Actual"), "forecast": ui.num("Forecast"),
            "abs_error": ui.num("|Error|"), "wape": st.column_config.NumberColumn("WAPE", format="%.1f%%"),
            "accuracy": ui.pct_bar("Accuracy"), "bias": st.column_config.NumberColumn("Bias", format="%+.1f%%"),
            "sku_hit_rate": st.column_config.NumberColumn("SKU แม่น≥80%", format="%.0f%%"),
            "mae": ui.num("MAE", 1), "rmse": ui.num("RMSE", 1)})
    with c2, st.container(border=True):
        ui.card_title("Bias (+ เกิน / − ขาด)")
        b2 = bd.dropna(subset=["bias"])
        fig = go.Figure(go.Bar(y=b2[dim], x=b2["bias"], orientation="h",
                               marker_color=[ui.C_OVER if v > 0 else ui.C_UNDER for v in b2["bias"]],
                               text=[ui.fmt_pct(v, 0, True) for v in b2["bias"]], textposition="outside"))
        fig.update_xaxes(tickformat=".0%", zeroline=True, zerolinecolor="#8B93C1")
        fig.update_yaxes(autorange="reversed", type="category")
        st.plotly_chart(ui.style(fig, max(260, 32 * len(b2) + 60), legend=False), use_container_width=True)

# ============================================================ ราย SKU
with tab3:
    sk = dp.sku_tracking(acc).merge(model.master[["sku", "name", "ABC_XYZ", "priority_tier", "category"]],
                                    on="sku", how="left")
    with st.container(border=True):
        ui.card_title("Forecast เทียบ Actual ราย SKU (หน่วย)")
        log = st.toggle("แกน log (ช่วยเมื่อขนาดต่างกันมาก)", value=True)
        p = sk[(sk["actual"] > 0) & (sk["forecast"] > 0)] if log else sk
        fig = px.scatter(p, x="actual", y="forecast", color="ABC_XYZ", hover_name="name",
                         hover_data={"sku": True, "actual": ":,.0f", "forecast": ":,.0f"},
                         log_x=log, log_y=log, labels={"actual": "Actual", "forecast": "Forecast"},
                         color_discrete_sequence=ui.SERIES)
        if len(p):
            lo = max(1, min(p["actual"].min(), p["forecast"].min()))
            hi = max(p["actual"].max(), p["forecast"].max())
            fig.add_scatter(x=[lo, hi], y=[lo, hi], mode="lines", line=dict(dash="dash", color="#8B93C1"),
                            showlegend=False, hoverinfo="skip")
        st.plotly_chart(ui.style(fig, 440), use_container_width=True)
        st.caption("เหนือเส้นประ = พยากรณ์เกิน · ใต้เส้นประ = พยากรณ์ขาด"
                   + (" · แกน log ไม่แสดงจุดที่เป็น 0" if log else ""))

    tbl = sk.assign(accuracy=sk["accuracy"] * 100)
    cols = ["sku", "name", "category", "ABC_XYZ", "priority_tier", "forecast", "actual", "sum_error",
            "bias", "accuracy", "tracking_signal"]
    cfg = {**ui.SKU_COLS, "category": ui.num("หมวด"), "forecast": ui.num("Forecast"), "actual": ui.num("Actual"),
           "sum_error": st.column_config.NumberColumn("Error", format="%+.0f"),
           "bias": st.column_config.NumberColumn("Bias", format="%+.2f", help="(F−A)/A"),
           "accuracy": ui.pct_bar("Accuracy"),
           "tracking_signal": st.column_config.NumberColumn(
               "Tracking signal", format="%+.1f",
               help="ผลรวม error ÷ MAD — เกิน ±4 = เอียงข้างเดียวต่อเนื่อง (ดูเมื่อมีหลายเดือน)")}
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        ui.card_title("⬆️ พยากรณ์เกินมากสุด")
        st.dataframe(tbl[tbl["sum_error"] > 0].sort_values("sum_error", ascending=False)[cols].head(50),
                     hide_index=True, use_container_width=True, column_config=cfg, height=420)
    with c2, st.container(border=True):
        ui.card_title("⬇️ พยากรณ์ขาดมากสุด")
        st.dataframe(tbl[tbl["sum_error"] < 0].sort_values("sum_error")[cols].head(50),
                     hide_index=True, use_container_width=True, column_config=cfg, height=420)
    st.download_button("⬇️ ดาวน์โหลดรายละเอียด SKU-เดือน (CSV)", acc.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"forecast_accuracy_{'_'.join(map(str, sel))}.csv", mime="text/csv")

# ============================================================ ยังไม่มี forecast
with tab4:
    act_sel = model.monthly[model.monthly["sku"].isin(skus - fc_skus) & model.monthly["month"].isin(sel)]
    nf = (act_sel.groupby("sku")["qty"].sum().reset_index()
          .merge(model.master[["sku", "name", "ABC_XYZ", "priority_tier", "category"]], on="sku", how="left")
          .sort_values("qty", ascending=False))
    st.info(f"มี **{len(nf):,} SKU** ที่ขายได้ในเดือนที่เลือกแต่ยังไม่มีในชีต Forecast — "
            "ไม่ได้นับรวมในตัวชี้วัด ควรพิจารณาเพิ่ม forecast ให้ตัวที่ขายสม่ำเสมอ")
    st.dataframe(nf, hide_index=True, use_container_width=True, height=480,
                 column_config={**ui.SKU_COLS, "qty": ui.num("ยอดขาย (หน่วย)"), "category": ui.num("หมวด")})

with st.expander("วิธีคำนวณ"):
    st.markdown("""
| ตัวชี้วัด | สูตร |
|---|---|
| WAPE | Σ\\|F − A\\| ÷ ΣA |
| Forecast Accuracy | 1 − WAPE (ต่ำสุด 0%) |
| Bias | (ΣF − ΣA) ÷ ΣA → + เกิน / − ขาด |
| SKU แม่น ≥ 80% | สัดส่วน SKU ที่ 1 − \\|F−A\\|/A ≥ 0.8 |
| Tracking signal | ΣError ÷ MAD (ใช้ได้เมื่อมี ≥ 3 เดือน) |
| MAE | ค่าเฉลี่ย \\|F − A\\| ต่อ SKU-เดือน (หน่วย) |
| RMSE | √ค่าเฉลี่ย (F − A)² — ลงโทษตัวที่คลาดมากๆ หนักกว่า MAE |

- **ทำไมไม่ใช้ F1 / ROC:** ใช้กับการทำนายแบบ ใช่/ไม่ใช่ (classification) ส่วน forecast ทำนายเป็นจำนวน จึงใช้ MAE / WAPE / Bias
- **Actual** = จำนวนจ่ายจากบิล **NV / IV** เท่านั้น · เทียบเฉพาะ SKU ที่อยู่ในชีต Forecast
- ผลรวมหน่วยรวมหลายหน่วยนับ (ม้วน/ชิ้น) — ดูแยกตาม *หมวด* เพื่อเทียบหน่วยเดียวกัน
- ล็อกตัวเลข forecast ก่อนเริ่มเดือน — ถ้าแก้ระหว่างเดือน accuracy จะดีเกินจริง
""")
