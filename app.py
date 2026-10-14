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
_missing = [f for f in ("stockout_watch", "pr_calc", "recent_avg") if not hasattr(dp, f)]
if _missing:
    st.error("ไฟล์ **dp_core.py** เป็นเวอร์ชันเก่า — อัปโหลดไฟล์ทั้งหมดจาก demand_dashboard.zip ชุดล่าสุดขึ้น GitHub "
             "แล้วกด Manage app → ⋮ → **Reboot app**")
    st.stop()

DEFAULT_SHEET = ("https://docs.google.com/spreadsheets/d/"
                 "1guwwOA_WvXpu_pHxBM6CZAbtuEw61-x-8Vsxbxglkrg/edit?usp=sharing")


@st.cache_data(ttl=600, show_spinner="กำลังดึงข้อมูล…")
def load_model(source: str, key: str, blob: bytes | None = None):
    if source == "gsheet":
        raw = dp.load_gsheet(key)
    elif source == "xlsx":
        raw = dp.load_xlsx(blob)
    else:
        raw = dp.load_csv_dir(key)
    return dp.build_model(raw), dt.datetime.now()


def secret_url() -> str:
    try:
        return st.secrets.get("sheet_url", DEFAULT_SHEET)
    except Exception:  # ไม่มีไฟล์ secrets
        return DEFAULT_SHEET


# ------------------------------------------------------------ หน้า
PAGES = [
    ("วางแผนความต้องการ", "views/forecast.py", "Forecast vs Actual", "🎯", True),
    ("วางแผนความต้องการ", "views/abc.py", "ABC-XYZ Grade", "🔤", False),
    ("วางแผนความต้องการ", "views/safety.py", "Safety Stock & ROP", "🛡️", False),
    ("วางแผนความต้องการ", "views/sku.py", "ดูราย SKU", "🔍", False),
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
model, loaded_at = None, None
with st.sidebar:
    with st.expander("⚙️ แหล่งข้อมูล", expanded=False):
        src = st.radio("แหล่งข้อมูล", ["Google Sheet", "อัปโหลด Excel", "โฟลเดอร์ CSV"],
                       index=2 if os.environ.get("DP_DATA_DIR") else 0, label_visibility="collapsed")
        try:
            if src == "Google Sheet":
                url = st.text_input("ลิงก์ Google Sheet", value=secret_url(),
                                    help="ต้องแชร์แบบ 'ทุกคนที่มีลิงก์สามารถดูได้'")
                model, loaded_at = load_model("gsheet", url)
            elif src == "อัปโหลด Excel":
                up = st.file_uploader("ไฟล์ .xlsx (File > Download จาก Google Sheet)", type=["xlsx"])
                if up is not None:
                    model, loaded_at = load_model("xlsx", up.name, up.getvalue())
            else:
                folder = st.text_input("โฟลเดอร์ CSV", value=os.environ.get("DP_DATA_DIR", "data"))
                model, loaded_at = load_model("csv", folder)
        except Exception as e:  # noqa: BLE001
            st.error(f"โหลดข้อมูลไม่สำเร็จ: {e}")

if model is None:
    st.info("เปิด ⚙️ แหล่งข้อมูล ที่แถบซ้ายเพื่อเลือกข้อมูล")
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
