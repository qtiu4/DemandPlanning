import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dp_core as dp
import ui

model, flt, skus = ui.ctx()
opts = flt[flt["sku"].isin(set(model.monthly["sku"]) | set(model.fc["sku"]))]
opts = opts.sort_values("value_rank", na_position="last")
ui.header("ดูราย SKU", "ยอดขายรายเดือน (NV/IV) เทียบ Forecast และพารามิเตอร์การวางแผน · หน่วย: จำนวน")
if not len(opts):
    st.info("ไม่มี SKU ตามตัวกรอง")
    st.stop()

labels = (opts["sku"] + " — " + opts["name"].fillna("").astype(str)).tolist()
pick = st.selectbox("เลือก SKU (พิมพ์ค้นหาได้)", labels)
sku = opts.iloc[labels.index(pick)]
code = sku["sku"]

c = st.columns(4)
ui.kpi(c[0], "ABC-XYZ", str(sku.get("ABC_XYZ", "-")), f"Tier: {sku.get('priority_tier', '-')}", ui.BLUE, "🔤")
ui.kpi(c[1], "เฉลี่ย/เดือน", ui.fmt_num(sku.get("mean_monthly_qty"), 1),
       f"CV {ui.fmt_num(sku.get('cv'), 2)} · ขาย {ui.fmt_num(sku.get('active_months'))} เดือน", ui.ORANGE, "📈")
ui.kpi(c[2], "Safety stock", ui.fmt_num(sku.get("safety_stock")),
       f"ROP {ui.fmt_num(sku.get('reorder_point'))} · Target {ui.fmt_num(sku.get('target_stock'))}", ui.TEAL, "🛡️")
ui.kpi(c[3], "Lead time", f"{ui.fmt_num(sku.get('lead_time_days'))} วัน",
       f"Status {sku.get('Status', '-')} · Production {sku.get('Production', '-')}", ui.PURPLE, "⏱️")
st.caption(f"ขายครั้งแรก {ui.fmt_date(sku.get('first_sale_date'))} · ขายล่าสุด {ui.fmt_date(sku.get('last_sale_date'))}"
           f" · ยอด 12 เดือน {ui.fmt_num(sku.get('qty_12m'))} หน่วย")

h = model.monthly[model.monthly["sku"] == code].set_index("month")["qty"]
f = model.fc[model.fc["sku"] == code].set_index("month")["forecast_qty"]
rng = dp.month_range(dp.month_add(model.last_month, -23), max([model.last_month] + f.index.tolist()))
df = pd.DataFrame({"month": rng, "label": [dp.month_label(m) for m in rng]})
df["actual"] = [h.get(m, 0.0) if m <= model.last_month else np.nan for m in rng]
df["forecast"] = df["month"].map(f)
df["ma3"] = df["actual"].rolling(3, min_periods=1).mean().where(df["month"] <= model.last_month)

with st.container(border=True):
    ui.card_title(f"{code} — ยอดขายรายเดือน (หน่วย)")
    fig = go.Figure()
    fig.add_bar(x=df["label"], y=df["actual"], name="ยอดขายจริง", marker_color=ui.BLUE, opacity=.85)
    fig.add_scatter(x=df["label"], y=df["forecast"], name="Forecast", mode="lines+markers",
                    line=dict(color=ui.ORANGE, width=3))
    fig.add_scatter(x=df["label"], y=df["ma3"], name="เฉลี่ยเคลื่อนที่ 3 ด.", mode="lines",
                    line=dict(color=ui.TEAL, dash="dot"))
    if pd.notna(sku.get("mean_monthly_qty")):
        ui.avg_line(fig, sku["mean_monthly_qty"], "เฉลี่ย", ui.PURPLE, "{:,.1f}")
    st.plotly_chart(ui.style(fig, 400), use_container_width=True)
if not len(f):
    st.warning("SKU นี้ยังไม่มีในชีต Forecast")

a1 = dp.accuracy_frame(model, skus=[code])
if len(a1):
    a1 = a1.assign(label=a1["month"].map(dp.month_label), accuracy=a1["accuracy"] * 100)
    st.dataframe(a1[["label", "forecast_qty", "actual_qty", "error", "accuracy", "direction"]],
                 hide_index=True, use_container_width=True, column_config={
                     "label": "เดือน", "forecast_qty": ui.num("Forecast"), "actual_qty": ui.num("Actual"),
                     "error": st.column_config.NumberColumn("Error", format="%+.0f"),
                     "accuracy": ui.pct_bar("Accuracy"), "direction": "ทิศทาง"})
