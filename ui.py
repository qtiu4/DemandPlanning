"""ธีม (โทนเข้มแบบ OEE dashboard), การ์ด KPI, header และรูปแบบตัวเลข"""
from __future__ import annotations

import base64
import datetime as _dt
from pathlib import Path

import pandas as pd
import streamlit as st

import dp_core as dp

# ------------------------------------------------------------ palette
BG, BG_SIDE, CARD, BORDER = "#0E1437", "#0A0F2C", "#151C4B", "#26306A"
TEXT, MUTED, GRID = "#E6E9F5", "#8B93C1", "#212B5E"
BLUE, ORANGE, TEAL, PURPLE, RED = "#38BDF8", "#F5A524", "#2DD4BF", "#A78BFA", "#F43F5E"
SERIES = [BLUE, ORANGE, TEAL, PURPLE, RED, "#F472B6", "#FACC15", "#60A5FA"]
C_ACT, C_FC, C_OVER, C_UNDER = BLUE, ORANGE, RED, TEAL

TH_MONTH_FULL = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600&display=swap');
/* ฟอนต์ Kanit เฉพาะข้อความ — ห้ามครอบ span ทั่วไป ไม่งั้นไอคอนจะกลายเป็นตัวหนังสือ (เช่น arrow_right) */
html, body, .stApp, p, li, label, input, textarea, button, h1, h2, h3, h4, h5, h6, td, th,
[data-testid="stMarkdownContainer"], [data-baseweb="select"] div, [data-baseweb="tab"], [role="option"] {{
  font-family: 'Kanit', sans-serif; }}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {{
  font-family: 'Material Symbols Rounded' !important; }}
/* dropdown / เมนูคอลัมน์ในตาราง: พื้นทึบ อยู่ชั้นบนสุด */
[data-baseweb="popover"] {{ z-index: 10000 !important; }}
[data-baseweb="popover"] ul, [data-baseweb="menu"], [data-testid="stDataFrameColumnMenu"] {{
  background: {CARD} !important; border: 1px solid {BORDER}; }}
[data-testid="stAppViewContainer"] {{ background: {BG}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: {BG_SIDE}; border-right: 1px solid #1B2352; }}
.block-container {{ padding-top: 2.2rem; max-width: 1400px; }}
h1, h2, h3, h4 {{ color: {TEXT}; }}

/* header card */
.dp-hdr {{ display:flex; align-items:center; gap:22px; background:linear-gradient(180deg,#18205A,{CARD});
  border:1px solid {BORDER}; border-radius:18px; padding:20px 28px; margin-bottom:6px; }}
.dp-hdr .logo {{ width:76px; height:76px; border-radius:14px; background:#fff; display:flex;
  align-items:center; justify-content:center; font-size:40px; overflow:hidden; flex-shrink:0; }}
.dp-hdr .logo img {{ width:100%; height:100%; object-fit:contain; }}
.dp-hdr .ttl {{ font-size:2.1rem; font-weight:600; color:#fff; line-height:1.15; }}
.dp-hdr .sub {{ color:{MUTED}; font-size:1rem; margin-top:4px; }}
.dp-hdr .rt {{ margin-left:auto; text-align:right; }}
.dp-hdr .rt .d {{ font-size:1.3rem; font-weight:600; color:#fff; }}
.dp-hdr .rt .u {{ color:{MUTED}; font-size:.9rem; }}

/* section title */
.dp-sec {{ display:flex; align-items:center; gap:10px; font-size:1.3rem; font-weight:600;
  color:{TEXT}; margin:18px 0 10px; }}
.dp-sec:before {{ content:""; width:9px; height:9px; border-radius:2px; background:{BLUE}; }}

/* KPI card */
.dp-kpi {{ position:relative; background:linear-gradient(180deg,#18205A,{CARD}); border:1px solid {BORDER};
  border-left:4px solid var(--c); border-radius:14px; padding:18px 20px 16px; min-height:138px; }}
.dp-kpi .t {{ color:{TEXT}; font-size:1.02rem; font-weight:500; }}
.dp-kpi .v {{ color:var(--c); font-size:2.35rem; font-weight:600; line-height:1.25; margin-top:6px; }}
.dp-kpi .s {{ color:{MUTED}; font-size:.86rem; margin-top:4px; }}
.dp-kpi .i {{ position:absolute; right:18px; top:14px; font-size:1.6rem; opacity:.55; filter:grayscale(.2); }}

/* card container (st.container(border=True)) */
[data-testid="stVerticalBlockBorderWrapper"] {{ background:linear-gradient(180deg,#151C4B,#121842);
  border:1px solid {BORDER} !important; border-radius:16px !important; }}
.dp-card-t {{ font-size:1.15rem; font-weight:600; color:#fff; margin:2px 0 4px; }}

/* tabs */
[data-baseweb="tab-list"] {{ gap:22px; border-bottom:1px solid {BORDER}; }}
[data-baseweb="tab"] {{ font-size:1.05rem; padding:6px 0; color:{TEXT}; }}

/* sidebar logo */
.dp-logo {{ width:200px; height:200px; margin:6px auto 14px; border-radius:50%;
  background:radial-gradient(circle at 50% 45%, #22306F 0%, #141C4D 62%, #0D1336 100%);
  box-shadow:0 0 0 1px #1E2A66, 0 0 40px rgba(56,189,248,.15); display:flex; flex-direction:column;
  align-items:center; justify-content:center; }}
.dp-logo .big {{ font-size:64px; font-weight:600; color:#5EEAD4; letter-spacing:4px; line-height:1;
  text-shadow:0 0 6px #22D3EE, 0 0 18px #0EA5E9, 0 0 32px #0284C7; }}
.dp-logo .sm {{ color:#E0F2FE; font-size:15px; margin-top:8px; text-shadow:0 0 6px #38BDF8; }}
.dp-foot {{ color:{MUTED}; font-size:.9rem; line-height:1.5; }}
[data-testid="stSidebarNav"] {{ display:none; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_logo():
    st.markdown('<div class="dp-logo"><div class="big">DP</div><div class="sm">Demand Planning</div></div>',
                unsafe_allow_html=True)


def _logo_html() -> str:
    for p in ("assets/logo.png", "assets/logo.jpg", "assets/logo.svg"):
        f = Path(p)
        if f.exists():
            mime = "image/svg+xml" if f.suffix == ".svg" else f"image/{f.suffix[1:]}"
            return f'<img src="data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}">'
    return "📦"


def thai_date(d: _dt.date | _dt.datetime) -> str:
    return f"{d.day} {TH_MONTH_FULL[d.month - 1]} {d.year + 543}"


def header(title: str, subtitle: str):
    c = st.session_state.get("ctx", {})
    loaded = c.get("loaded_at")
    upd = f"อัปเดตข้อมูล {loaded:%d/%m/%Y %H:%M}" if loaded else ""
    st.markdown(f"""
<div class="dp-hdr"><div class="logo">{_logo_html()}</div>
  <div><div class="ttl">{title}</div><div class="sub">{subtitle}</div></div>
  <div class="rt"><div class="d">{thai_date(_dt.date.today())}</div><div class="u">{upd}</div></div>
</div>""", unsafe_allow_html=True)


def section(text: str):
    st.markdown(f'<div class="dp-sec">{text}</div>', unsafe_allow_html=True)


def card_title(text: str):
    st.markdown(f'<div class="dp-card-t">{text}</div>', unsafe_allow_html=True)


def kpi(col, title: str, value: str, sub: str = "", color: str = BLUE, icon: str = ""):
    col.markdown(f"""<div class="dp-kpi" style="--c:{color}"><div class="i">{icon}</div>
<div class="t">{title}</div><div class="v">{value}</div><div class="s">{sub}</div></div>""",
                 unsafe_allow_html=True)


# ------------------------------------------------------------ plotly
def style(fig, height=360, legend=True):
    fig.update_layout(
        template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Kanit, sans-serif", color="#C9D1F5", size=13), colorway=SERIES,
        margin=dict(l=8, r=8, t=30, b=8), showlegend=legend,
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=CARD, bordercolor=BORDER, font_family="Kanit"))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def avg_line(fig, y, text, color=ORANGE, fmt="{:,.0f}"):
    fig.add_hline(y=y, line_dash="dash", line_color=color, line_width=1.5,
                  annotation_text=f"{text} {fmt.format(y)}", annotation_position="top left",
                  annotation_font_color=color)


# ------------------------------------------------------------ format
def fmt_num(v, d=0):
    return "-" if v is None or pd.isna(v) else f"{v:,.{d}f}"


def fmt_pct(v, d=1, sign=False):
    if v is None or pd.isna(v):
        return "-"
    return f"{v*100:+.{d}f}%" if sign else f"{v*100:.{d}f}%"


def fmt_month(v):
    return "-" if v is None or pd.isna(v) else dp.month_label(int(v))


def fmt_date(v):
    return "-" if v is None or pd.isna(v) else pd.Timestamp(v).strftime("%d/%m/%Y")


def num(label, d=0, help=None):
    return st.column_config.NumberColumn(label, format="localized" if d == 0 else f"%.{d}f", help=help)


def pct_bar(label, help=None):
    """ใช้กับคอลัมน์ที่คูณ 100 แล้ว"""
    return st.column_config.ProgressColumn(label, format="%.0f%%", min_value=0, max_value=100, help=help)


SKU_COLS = {"sku": "รหัส", "name": "ชื่อสินค้า", "ABC_XYZ": "ABC-XYZ", "priority_tier": "Tier"}


def ctx():
    c = st.session_state["ctx"]
    return c["model"], c["flt"], c["skus"]
