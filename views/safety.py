import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import dp_core as dp
import ui

model, flt, skus = ui.ctx()
ui.header("Safety Stock & Reorder Point",
          "ระดับสต๊อกเผื่อและจุดสั่งผลิตราย SKU · หน่วย: จำนวน · ค่าจากชีต Cal ABC_XYZ")

m = flt[flt["safety_stock"].fillna(0) > 0].copy()
with np.errstate(divide="ignore", invalid="ignore"):
    m["ss_months"] = m["safety_stock"] / m["mean_monthly_qty"]
plan = dp.planning_table(model)
fcols = [c for c in plan.columns if c.startswith("F ")]
m = m.merge(plan[["sku"] + fcols + ["fc_vs_mean", "review_flag"]], on="sku", how="left")

c = st.columns(4)
ui.kpi(c[0], "SKU ที่มี Safety stock", f"{len(m):,}", f"จาก {len(flt):,} SKU ที่เลือก", ui.BLUE, "🛡️")
ui.kpi(c[1], "Σ Safety stock", ui.fmt_num(m["safety_stock"].sum()),
       f"Σ ROP {ui.fmt_num(m['reorder_point'].sum())} หน่วย", ui.ORANGE, "📦")
lt = m["lead_time_days"]
ui.kpi(c[2], "Lead time เฉลี่ย", f"{ui.fmt_num(lt.mean())} วัน",
       f"ต่ำสุด {ui.fmt_num(lt.min())} · สูงสุด {ui.fmt_num(lt.max())} วัน", ui.TEAL, "⏱️")
hi = (m["ss_months"] > 2).sum()
ui.kpi(c[3], "SS เกิน 2 เดือนขาย", f"{hi:,} SKU", "ควรรีวิว (มักเป็นกลุ่ม Z)", ui.PURPLE, "⚠️")

tab0, tab1, tab2 = st.tabs(["🧮 คำนวณ PR", "ภาพรวม", "ตารางราย SKU"])

# ============================================================ คำนวณ PR
with tab0:
    st.markdown("กรอก **รหัสสินค้า** และ **สต๊อกคงเหลือปัจจุบัน** (เพิ่มแถวได้ หรือวางจาก Excel) "
                "ระบบจะเทียบกับ Safety stock / ROP แล้วแนะนำจำนวนที่ควรเปิด PR ผลิตหรือสั่งซื้อ")
    sku_opts = model.master.sort_values("value_rank", na_position="last")["sku"].tolist()
    if "pr_rows" not in st.session_state:
        st.session_state["pr_rows"] = pd.DataFrame({"sku": [None] * 5, "on_hand": [0.0] * 5,
                                                    "on_order": [0.0] * 5, "lot_size": [1.0] * 5})
    c1, c2 = st.columns([4, 1])
    with c2:
        review = st.number_input("รอบทบทวน (เดือน)", min_value=0.25, max_value=6.0, value=1.0, step=0.25,
                                 help="ความถี่ที่วางแผนสั่ง/ผลิต เช่น เดือนละครั้ง = 1")
    with c1:
        rows = st.data_editor(
            st.session_state["pr_rows"], num_rows="dynamic", use_container_width=True, key="pr_editor",
            column_config={
                "sku": st.column_config.SelectboxColumn("รหัสสินค้า", options=sku_opts, required=False,
                                                        help="พิมพ์ค้นหารหัสได้"),
                "on_hand": st.column_config.NumberColumn("คงเหลือปัจจุบัน", min_value=0, step=1, format="%d"),
                "on_order": st.column_config.NumberColumn("ค้างรับ (PR/PO เดิม)", min_value=0, step=1, format="%d"),
                "lot_size": st.column_config.NumberColumn("ปัดทีละ (lot)", min_value=1, step=1, format="%d",
                                                          help="ขั้นต่ำ/ขนาดล็อต เช่น ผลิตทีละ 50 ม้วน"),
            })
    res = dp.pr_calc(model, rows, review)
    if len(res) and "pr_qty" in res:
        need = res[res["pr_qty"] > 0]
        c = st.columns(4)
        ui.kpi(c[0], "SKU ที่ต้องเปิด PR", f"{len(need):,}", f"จาก {len(res):,} รหัสที่กรอก", ui.RED, "🧾")
        ui.kpi(c[1], "รวมจำนวน PR", ui.fmt_num(need["pr_qty"].sum()), "หน่วย", ui.ORANGE, "📦")
        ui.kpi(c[2], "ต่ำกว่า Safety stock", f"{res['status'].astype(str).str.contains('ต่ำกว่า').sum():,}",
               "ต้องเร่งด่วน", ui.PURPLE, "🚨")
        ui.kpi(c[3], "ยังไม่ต้องสั่ง", f"{(res['status'] == 'ยังไม่ต้องสั่ง').sum():,}", "สต๊อกเพียงพอ", ui.TEAL, "✅")
        with st.container(border=True):
            ui.card_title("ผลการคำนวณ")
            show = res.copy()
            show["cover_months"] = show["cover_months"].replace(np.inf, np.nan)
            st.dataframe(show, hide_index=True, use_container_width=True, column_config={
                **ui.SKU_COLS, "on_hand": ui.num("คงเหลือ"), "on_order": ui.num("ค้างรับ"),
                "demand_month": ui.num("ความต้องการ/ด.", 1), "demand_basis": "ใช้ข้อมูลจาก",
                "lead_time_days": ui.num("LT (วัน)"), "safety_stock": ui.num("SS"), "rop": ui.num("ROP"),
                "target": ui.num("Target"), "cover_months": ui.num("พอขายกี่เดือน", 1),
                "status": "สถานะ", "pr_qty": ui.num("➡️ เปิด PR (หน่วย)")})
            st.download_button("⬇️ ดาวน์โหลดผล (CSV)", show.to_csv(index=False).encode("utf-8-sig"),
                               file_name="pr_suggestion.csv", mime="text/csv")
    else:
        st.info("เลือกรหัสสินค้าในตารางด้านบนเพื่อเริ่มคำนวณ")
    with st.expander("วิธีคำนวณ PR"):
        st.markdown("""
- **ความต้องการต่อเดือน** = ค่าเฉลี่ย Forecast ของเดือนข้างหน้าที่ครอบคลุม *Lead time + รอบทบทวน*
  (ถ้ายังไม่มี forecast ใช้ค่าเฉลี่ยในอดีต)
- **ROP** = ความต้องการ/ด. × Lead time ÷ 30 + Safety stock
- **Target** = ความต้องการ/ด. × (Lead time ÷ 30 + รอบทบทวน) + Safety stock
- ถ้า **คงเหลือ + ค้างรับ ≤ ROP** → **เปิด PR = Target − (คงเหลือ + ค้างรับ)** แล้วปัดขึ้นตาม lot
- สินค้า A4-Fading จะไม่แนะนำให้สั่งเพิ่ม · Safety stock / Lead time ดึงจากชีต Cal ABC_XYZ
""")

with tab1:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        ui.card_title("Safety stock ตาม Tier (หน่วย)")
        t = m.groupby("priority_tier").agg(SKU=("sku", "count"), SS=("safety_stock", "sum")).reset_index()
        fig = go.Figure(go.Bar(x=t["priority_tier"], y=t["SS"], marker_color=ui.SERIES[:len(t)],
                               text=[f"{v:,.0f}<br>{n} SKU" for v, n in zip(t["SS"], t["SKU"])],
                               textposition="outside"))
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(ui.style(fig, 360, legend=False), use_container_width=True)
    with c2, st.container(border=True):
        ui.card_title("SS คิดเป็นกี่เดือนของยอดขายเฉลี่ย")
        h = m["ss_months"].replace(np.inf, np.nan).dropna().clip(upper=6)
        fig = px.histogram(h, nbins=24, color_discrete_sequence=[ui.BLUE])
        fig.add_vline(x=1.0, line_dash="dash", line_color=ui.ORANGE, annotation_text="1 เดือน",
                      annotation_font_color=ui.ORANGE)
        fig.update_xaxes(title="Safety stock ÷ เฉลี่ย/เดือน (ตัดที่ 6)")
        fig.update_yaxes(title="จำนวน SKU")
        st.plotly_chart(ui.style(fig, 360, legend=False), use_container_width=True)

    if fcols:
        with st.container(border=True):
            ui.card_title("Forecast เดือนหน้าเทียบค่าเฉลี่ย — ตัวที่ควรตรวจก่อนวางแผนผลิต")
            rv = m[m["review_flag"].astype(str).str.len() > 0].sort_values("value_rank", na_position="last")
            st.dataframe(rv[["sku", "name", "ABC_XYZ", "priority_tier", "mean_monthly_qty"] + fcols +
                            ["fc_vs_mean", "safety_stock", "reorder_point", "review_flag"]],
                         hide_index=True, use_container_width=True, height=360, column_config={
                             **ui.SKU_COLS, "mean_monthly_qty": ui.num("เฉลี่ย/ด.", 1),
                             **{f: ui.num(f) for f in fcols},
                             "fc_vs_mean": ui.num("F ÷ เฉลี่ย", 2), "safety_stock": ui.num("SS"),
                             "reorder_point": ui.num("ROP"), "review_flag": "ควรตรวจ"})

with tab2:
    cols = ["sku", "name", "category", "ABC_XYZ", "priority_tier", "mean_monthly_qty", "std_monthly_qty", "cv",
            "lead_time_days", "safety_stock", "ss_months", "reorder_point", "target_stock"] + fcols
    tbl = m.sort_values("value_rank", na_position="last")[[c for c in cols if c in m]]
    st.dataframe(tbl, hide_index=True, use_container_width=True, height=560, column_config={
        **ui.SKU_COLS, "category": ui.num("หมวด"), "mean_monthly_qty": ui.num("เฉลี่ย/ด.", 1),
        "std_monthly_qty": ui.num("SD/ด.", 1), "cv": ui.num("CV", 2), "lead_time_days": ui.num("LT (วัน)"),
        "safety_stock": ui.num("SS"), "ss_months": ui.num("SS = กี่เดือน", 1),
        "reorder_point": ui.num("ROP"), "target_stock": ui.num("Target"), **{f: ui.num(f) for f in fcols}})
    st.download_button("⬇️ ดาวน์โหลด (CSV)", tbl.to_csv(index=False).encode("utf-8-sig"),
                       file_name="safety_stock.csv", mime="text/csv")

with st.expander("สูตรที่ใช้"):
    st.markdown("""
- **Safety stock** = Z × SD รายเดือน × √(Lead time วัน ÷ 30) — Z ตาม service level กลุ่ม A/B/C
- **Reorder point** = เฉลี่ยต่อเดือน × (Lead time ÷ 30) + Safety stock
- **Target stock** = เฉลี่ยต่อเดือน × (Lead time ÷ 30 + รอบทบทวน) + Safety stock
- **SS = กี่เดือน** = Safety stock ÷ เฉลี่ยต่อเดือน — สูงผิดปกติมักเป็นกลุ่ม Z ที่ควรรีวิวด้วยคน
- ธง *ควรตรวจ*: forecast เดือนหน้าสูง/ต่ำกว่าค่าเฉลี่ยเกิน 50%, กลุ่ม A ไม่มี forecast, Fading แต่ยังมี forecast
""")
