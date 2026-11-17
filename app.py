"""
Demand Planning Dashboard — Streamlit (เลือกหัวข้อที่เมนูซ้าย)
รัน:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import os

import streamlit as st

import dp_core as dp
import ui

st.set_page_config(page_title="Demand Planning", page_icon="📦", layout="wide")
ui.inject_css()

# ตรวจว่าไฟล์ทุกตัวเป็นรุ่นเดียวกัน (กันกรณีอัปโหลดไฟล์ขึ้น GitHub ไม่ครบ)
_missing = [f for f in ("stockout_watch", "pr_calc", "recent_avg", "production_plan", "week_shares") if not hasattr(dp, f)]
if _missing:
    st.error("ไฟล์ **dp_core.py** เป็นเวอร์ชันเก่า — อัปโหลดไฟล์ทั้งหมดจาก demand_dashboard.zip ชุดล่าสุดขึ้น GitHub "
             "แล้วกด Manage app → ⋮ → **Reboot app**")
    st.stop()

def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # ไม่มีไฟล์ secrets
        return default


@st.cache_data(ttl=600, show_spinner="กำลังดึงข้อมูล…")
def load_model(source: str, key: str, blob: bytes | None = None):
    if source == "gsheet":
        sa = _secret("gcp_service_account")
        raw = dp.load_gsheet(_secret("sheet_url", ""), service_account=dict(sa) if sa else None)
    elif source == "xlsx":
        raw = dp.load_xlsx(blob)
    else:
        raw = dp.load_csv_dir(key)
    return dp.build_model(raw), dt.datetime.now()


# ------------------------------------------------------------ หน้า
PAGES = [
    ("วางแผนความต้องการ", "views/forecast.py", "Forecast vs Actual", "🎯", True),
    ("วางแผนความต้องการ", "views/abc.py", "ABC-XYZ Grade", "🔤", False),
    ("วางแผนความต้องการ", "views/safety.py", "Safety Stock & ROP", "🛡️", False),
    ("วางแผนความต้องการ", "views/sku.py", "ดูราย SKU", "🔍", False),
    ("วางแผนความต้องการ", "views/assistant.py", "ผู้ช่วยวางแผน (AI)", "🤖", False),
    ("สินค้าคงคลัง", "views/nonmoving.py", "Non-moving Inventory", "📦", False),
    ("ระบบ", "views/quality.py", "คุณภาพข้อมูล", "🧹", False),
]
pages = {}
for grp, path, title, icon, default in PAGES:
    pages.setdefault(grp, []).append(st.Page(path, title=title, icon=icon, default=default))
nav = st.navigation(pages, position="hidden")

with st.sidebar:
    ui.sidebar_logo()
    for grp, items in pages.items():
        st.caption(grp)
        for p in items:
            st.page_link(p, label=p.title, icon=p.icon)
    st.divider()

# ------------------------------------------------------------ โหลดข้อมูล
# ลิงก์ชีตอยู่ใน Secrets เท่านั้น (sheet_url) — ไม่แสดงบนหน้าเว็บและไม่อยู่ในโค้ด
# ทดสอบในเครื่อง: ตั้ง DP_DATA_DIR=<โฟลเดอร์ CSV>
model, loaded_at = None, None
try:
    if os.environ.get("DP_DATA_DIR"):
        model, loaded_at = load_model("csv", os.environ["DP_DATA_DIR"])
    elif _secret("sheet_url"):
        model, loaded_at = load_model("gsheet", "secret")
    else:
        st.error("ยังไม่ได้ตั้งค่าแหล่งข้อมูล — ใส่ `sheet_url` ใน Secrets ของแอป (Manage app → Settings → Secrets)")
        st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"โหลดข้อมูลไม่สำเร็จ: {e}")
    st.stop()

# ------------------------------------------------------------ ตัวกรอง (ใช้ทุกหน้า)
master = model.master
with st.sidebar:
    st.markdown("### ตัวกรอง")

    def ms(label, col):
        opts = sorted(master[col].dropna().astype(str).unique().tolist())
        return st.multiselect(label, opts, default=[], key=f"f_{col}", placeholder="ทั้งหมด")

    cats = sorted(master["category"].dropna().astype(int).unique().tolist())
    f_cat = st.multiselect("หมวด", cats, default=[], key="f_cat", placeholder="ทั้งหมด")
    f_abc = ms("ABC", "ABC")
    f_xyz = ms("XYZ", "XYZ")
    f_tier = ms("Priority tier", "priority_tier")
    f_prod = ms("Production", "Production")
    no_inactive = st.toggle("ไม่รวม SKU ที่ Status = Inactive", value=False, key="f_inactive")

flt = master.copy()
for col, sel in [("ABC", f_abc), ("XYZ", f_xyz), ("priority_tier", f_tier), ("Production", f_prod)]:
    if sel:
        flt = flt[flt[col].astype(str).isin(sel)]
if f_cat:
    flt = flt[flt["category"].isin(f_cat)]
if no_inactive:
    flt = flt[flt["Status"].astype(str).str.lower() != "inactive"]

with st.sidebar:
    st.divider()
    st.markdown(
        f'<div class="dp-foot">SKU ที่เลือก: {len(flt):,} / {len(master):,}<br>'
        f'ยอดขาย (NV/IV) ถึง {model.last_date:%d/%m/%Y}<br>'
        f'ดึงข้อมูลล่าสุด: {loaded_at:%d/%m/%Y %H:%M} (อัปเดตอัตโนมัติทุก 10 นาที)</div>',
        unsafe_allow_html=True)
    if st.button("ดึงข้อมูลใหม่ตอนนี้"):
        st.cache_data.clear()
        st.rerun()

st.session_state["ctx"] = {"model": model, "flt": flt, "skus": set(flt["sku"]), "loaded_at": loaded_at}
nav.run()
