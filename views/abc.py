import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui

model, flt, skus = ui.ctx()
cfg = model.config
ui.header("ABC-XYZ Grade",
          f"จัดกลุ่มสินค้าตามมูลค่า (ABC) และความสม่ำเสมอของดีมานด์ (XYZ) · ช่วงวิเคราะห์ "
          f"{ui.fmt_month(cfg.get('start_month'))} – {ui.fmt_month(cfg.get('end_month'))} "
          f"({ui.fmt_num(cfg.get('n_months'))} เดือน)")

g = flt[flt["ABC"].isin(["A", "B", "C"])]
tot_v = g["total_value"].sum()
c = st.columns(4)
for i, (k, colr, ic) in enumerate([("A", ui.BLUE, "🥇"), ("B", ui.ORANGE, "🥈"), ("C", ui.PURPLE, "🥉")]):
    sub = g[g["ABC"] == k]
    ui.kpi(c[i], f"กลุ่ม {k}", f"{len(sub):,} SKU",
           f"{ui.fmt_pct(sub['total_value'].sum() / tot_v if tot_v else None)} ของมูลค่า · "
           f"{ui.fmt_pct(len(sub) / len(g) if len(g) else None)} ของจำนวน SKU", colr, ic)
ui.kpi(c[3], "A1-Core (A แท้)", f"{(g['priority_tier'] == 'A1-Core').sum():,} SKU",
       "AX/AY ขายบ่อย ยังขายอยู่", ui.TEAL, "⭐")

tab0, tab1, tab2, tab3 = st.tabs(["🗺️ Treemap", "ภาพรวม", "Priority tier", "รายการ SKU"])

with tab0:
    c1, c2, c3 = st.columns([2, 2, 1])
    size_lbl = c1.radio("ขนาดกล่องตาม", ["มูลค่าขาย (บาท)", "จำนวนขายเฉลี่ย/เดือน (หน่วย)"], horizontal=True)
    color_lbl = c2.radio("สีตาม", ["ABC", "ABC-XYZ", "Priority tier"], horizontal=True)
    depth = c3.select_slider("แสดงลึก", options=[2, 3], value=3, format_func=lambda d: {2: "ถึงกลุ่ม", 3: "ถึง SKU"}[d])
    size_col = "total_value" if size_lbl.startswith("มูลค่า") else "mean_monthly_qty"
    color_col = {"ABC": "ABC", "ABC-XYZ": "ABC_XYZ", "Priority tier": "priority_tier"}[color_lbl]
    t = g[g[size_col].fillna(0) > 0].copy()
    t["หมวด"] = "หมวด " + t["category"].map(lambda x: str(int(x)) if pd.notna(x) else "-")
    t["กลุ่ม"] = "กลุ่ม " + t["sku"].str.split("-").str[0]
    t["รหัส"] = (t["sku"] + "<br>" + t["mean_monthly_qty"].map(lambda v: f"{v:,.0f}") + " /ด. · "
                 + t["ABC_XYZ"].astype(str))
    t["ทั้งหมด"] = "สินค้าทั้งหมด"
    cmap = {"A": ui.BLUE, "B": ui.ORANGE, "C": ui.PURPLE, "AX": "#0EA5E9", "AY": "#38BDF8", "AZ": "#7DD3FC",
            "BX": "#D97706", "BY": "#F59E0B", "BZ": "#FCD34D", "CX": "#7C3AED", "CY": "#A78BFA", "CZ": "#C4B5FD",
            "A1-Core": ui.TEAL, "A2-Volatile": ui.ORANGE, "A3-Irregular": ui.PURPLE, "A4-Fading": "#64748B",
            "NEW": ui.RED, "นอกกลุ่ม A": "#334155", "(?)": "#18205A"}
    fig = px.treemap(t, path=["ทั้งหมด", "หมวด", "กลุ่ม", "รหัส"], values=size_col, color=color_col,
                     color_discrete_map=cmap, maxdepth=depth + 1,
                     hover_data={"name": True, "mean_monthly_qty": ":,.1f", "ABC_XYZ": True})
    unit = "บาท" if size_col == "total_value" else "หน่วย/ด."
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{value:,.0f} " + unit + "<br>%{percentRoot:.1%}",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + unit + "<br>%{percentRoot:.1%} ของทั้งหมด"
                      "<br>%{percentParent:.1%} ของกลุ่มบน<extra></extra>",
        marker=dict(line=dict(color=ui.BG, width=1.5)), root_color=ui.CARD, tiling=dict(pad=3))
    with st.container(border=True):
        ui.card_title("หมวดสินค้า → กลุ่มรหัส → SKU  (คลิกกล่องเพื่อเจาะลึก · คลิกแถบด้านบนเพื่อย้อนกลับ)")
        st.plotly_chart(ui.style(fig, 640, legend=False), use_container_width=True)
        st.caption("ในกล่อง SKU: รหัส · ยอดขายเฉลี่ยต่อเดือน (หน่วย) · กลุ่ม ABC-XYZ — กลุ่มรหัส = 3 หลักแรกของรหัสสินค้า")
    sub = (t.groupby(["หมวด", "กลุ่ม"]).agg(SKU=("sku", "count"), มูลค่า=("total_value", "sum"),
                                         เฉลี่ย=("mean_monthly_qty", "sum"),
                                         A=("ABC", lambda x: (x == "A").sum())).reset_index()
           .sort_values("มูลค่า", ascending=False))
    with st.expander("ตารางสรุปตามกลุ่มรหัส"):
        st.dataframe(sub, hide_index=True, use_container_width=True, column_config={
            "มูลค่า": ui.num("มูลค่า (บาท)"), "เฉลี่ย": ui.num("Σ เฉลี่ย/ด. (หน่วย)"), "A": ui.num("SKU กลุ่ม A")})

with tab1:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        ui.card_title("ABC × XYZ (จำนวน SKU / สัดส่วนมูลค่า)")
        mx = g[g["XYZ"].isin(["X", "Y", "Z", "N"])]
        if len(mx):
            ct = pd.crosstab(mx["ABC"], mx["XYZ"])
            val = mx.pivot_table(index="ABC", columns="XYZ", values="total_value", aggfunc="sum").reindex_like(ct)
            share = val / val.sum().sum()
            txt = ct.astype(str) + " SKU<br>" + (share * 100).round(1).astype(str) + "%"
            hm = go.Figure(go.Heatmap(z=share.values, x=ct.columns, y=ct.index, text=txt.values,
                                      texttemplate="%{text}", showscale=False, xgap=4, ygap=4,
                                      colorscale=[[0, "#18205A"], [0.5, "#1D6FA5"], [1, "#38BDF8"]],
                                      hovertemplate="%{y}%{x}<br>%{text}<extra></extra>"))
            hm.update_yaxes(autorange="reversed", showgrid=False)
            hm.update_xaxes(showgrid=False, side="top")
            st.plotly_chart(ui.style(hm, 360, legend=False), use_container_width=True)
    with c2, st.container(border=True):
        ui.card_title("Pareto มูลค่าสะสม")
        p = g.sort_values("total_value", ascending=False).reset_index(drop=True)
        p["cum"] = p["total_value"].cumsum() / tot_v
        p["rank"] = p.index + 1
        fig = go.Figure()
        for k, colr, fc in [("A", ui.BLUE, "rgba(56,189,248,.35)"), ("B", ui.ORANGE, "rgba(245,165,36,.3)"),
                            ("C", ui.PURPLE, "rgba(167,139,250,.25)")]:
            s = p[p["ABC"] == k]
            fig.add_scatter(x=s["rank"], y=s["cum"], mode="lines", fill="tozeroy", name=k,
                            line=dict(color=colr, width=2), fillcolor=fc,
                            hovertemplate="อันดับ %{x}<br>สะสม %{y:.1%}<extra></extra>")
        for y in (0.8, 0.95):
            fig.add_hline(y=y, line_dash="dash", line_color="#8B93C1", annotation_text=f"{y:.0%}",
                          annotation_position="bottom right")
        fig.update_yaxes(tickformat=".0%", range=[0, 1.02])
        fig.update_xaxes(title="อันดับ SKU ตามมูลค่า")
        st.plotly_chart(ui.style(fig, 360), use_container_width=True)

with tab2:
    with st.container(border=True):
        ui.card_title("สรุปตาม Priority tier")
        tg = flt.groupby("priority_tier").agg(SKU=("sku", "count"), มูลค่า=("total_value", "sum"),
                                              เฉลี่ย=("mean_monthly_qty", "sum"),
                                              ss=("safety_stock", "sum")).reset_index()
        tg["สัดส่วน"] = tg["มูลค่า"] / tg["มูลค่า"].sum() * 100
        st.dataframe(tg, hide_index=True, use_container_width=True, column_config={
            "priority_tier": "Tier", "มูลค่า": ui.num("มูลค่าในช่วงวิเคราะห์ (บาท)"),
            "เฉลี่ย": ui.num("Σ เฉลี่ย/เดือน (หน่วย)"), "ss": ui.num("Σ Safety stock (หน่วย)"),
            "สัดส่วน": ui.pct_bar("สัดส่วนมูลค่า")})
    st.markdown("""
| Tier | เงื่อนไข | วิธีดูแล |
|---|---|---|
| **A1-Core** | AX/AY ขายบ่อย ยังขายอยู่ | พยากรณ์ด้วยโมเดล (SARIMAX) เติมสต๊อกตามรอบ |
| **A2-Volatile** | AZ ขายบ่อย | รีวิวทุกเดือน ถือ SS มากขึ้น ถามฝ่ายขายเรื่องออเดอร์ใหญ่ |
| **A3-Irregular** | ขาย < 2/3 ของจำนวนเดือน | SBA หรือผลิตตามออเดอร์ |
| **A4-Fading** | ไม่ขาย 3 เดือนล่าสุด | ไม่ควรผลิตเพิ่ม |
| **NEW** | ประวัติสั้นกว่าเกณฑ์ | ใช้ค่าเฉลี่ยล่าสุด + ข้อมูลจากฝ่ายขาย |
""")

with tab3:
    cols = ["sku", "name", "category", "ABC", "XYZ", "ABC_XYZ", "priority_tier", "total_value", "cum_pct_value",
            "mean_monthly_qty", "cv", "active_months", "n_months_eff", "last_sale_month", "Status"]
    cols = [c for c in cols if c in flt]
    tbl = g[cols].sort_values("total_value", ascending=False).copy()
    tbl["cum_pct_value"] = tbl["cum_pct_value"] * 100
    tbl["last_sale_month"] = tbl["last_sale_month"].map(ui.fmt_month)
    st.dataframe(tbl, hide_index=True, use_container_width=True, height=520, column_config={
        **ui.SKU_COLS, "category": ui.num("หมวด"), "total_value": ui.num("มูลค่า (บาท)"),
        "cum_pct_value": st.column_config.NumberColumn("% สะสม", format="%.1f%%"),
        "mean_monthly_qty": ui.num("เฉลี่ย/เดือน (หน่วย)", 1), "cv": ui.num("CV", 2),
        "active_months": ui.num("เดือนที่ขาย"), "n_months_eff": ui.num("เดือนที่นับ"),
        "last_sale_month": "ขายล่าสุด"})
    st.download_button("⬇️ ดาวน์โหลด (CSV)", tbl.to_csv(index=False).encode("utf-8-sig"),
                       file_name="abc_xyz.csv", mime="text/csv")
