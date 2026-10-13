import streamlit as st

import ui

model, flt, skus = ui.ctx()
ui.header("คุณภาพข้อมูล", "รายการที่ควรแก้ในชีต เพื่อให้ตัวเลขในหน้าอื่นถูกต้อง · หน้านี้ไม่ใช้ตัวกรอง")

iss = model.issues
m = model.master
fc_skus = set(model.fc["sku"])
dup = iss.get("forecast_duplicate")
never = iss.get("forecast_never_sold")
a_nofc = m[(m["ABC"] == "A") & m["priority_tier"].isin(["A1-Core", "A2-Volatile", "A3-Irregular", "NEW"])
           & ~m["sku"].isin(fc_skus)].sort_values("value_rank")
inact = m[(m["Status"].astype(str).str.lower() == "inactive") & (m["qty_12m"] > 0)]
fad = m[(m["priority_tier"] == "A4-Fading") & m["sku"].isin(
    model.fc[(model.fc["month"] > model.last_month) & (model.fc["forecast_qty"] > 0)]["sku"])]

c = st.columns(4)
ui.kpi(c[0], "รหัสซ้ำใน Forecast", f"{dup['sku'].nunique() if dup is not None and len(dup) else 0}",
       "ระบบใช้แถวแรก", ui.RED, "⚠️")
ui.kpi(c[1], "Forecast แต่ไม่เคยขาย", f"{len(never) if never is not None else 0}",
       "สินค้าใหม่ หรือรหัสผิด", ui.ORANGE, "❓")
ui.kpi(c[2], "กลุ่ม A ไม่มี Forecast", f"{len(a_nofc)}", "ควรเพิ่มในชีต Forecast", ui.BLUE, "🎯")
ui.kpi(c[3], "Inactive แต่ยังขายอยู่", f"{len(inact)}", "มียอดใน 12 เดือน · เช็กชีต Info", ui.PURPLE, "🔁")

t = st.tabs(["รหัสซ้ำ", "Forecast ไม่เคยขาย", "A ไม่มี Forecast", "Inactive แต่ยังขาย", "Fading มี Forecast"])
with t[0]:
    if dup is not None and len(dup):
        st.dataframe(dup, hide_index=True, use_container_width=True, column_config={"fc_name": "ชื่อใน Forecast"})
    else:
        st.success("ไม่มีรหัสซ้ำ")
with t[1]:
    if never is not None and len(never):
        st.dataframe(never, hide_index=True, use_container_width=True, column_config={"fc_name": "ชื่อใน Forecast"})
    else:
        st.success("ไม่มี")
with t[2]:
    st.dataframe(a_nofc[["sku", "name", "ABC_XYZ", "priority_tier", "value_rank", "mean_monthly_qty"]],
                 hide_index=True, use_container_width=True,
                 column_config={**ui.SKU_COLS, "value_rank": ui.num("อันดับมูลค่า"),
                                "mean_monthly_qty": ui.num("เฉลี่ย/ด.", 1)})
with t[3]:
    st.dataframe(inact.sort_values("qty_12m", ascending=False)[["sku", "name", "ABC_XYZ", "qty_12m", "last_sale_date"]],
                 hide_index=True, use_container_width=True,
                 column_config={**ui.SKU_COLS, "qty_12m": ui.num("ขาย 12 ด. (หน่วย)"),
                                "last_sale_date": st.column_config.DateColumn("ขายล่าสุด", format="DD/MM/YYYY")})
with t[4]:
    if len(fad):
        st.dataframe(fad[["sku", "name", "ABC_XYZ", "last_sale_date"]], hide_index=True, use_container_width=True)
    else:
        st.success("ไม่มี")
