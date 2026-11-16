import hashlib
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_tools
import dp_core as dp
import ui

model, flt, skus = ui.ctx()
ui.header("ผู้ช่วยวางแผน", "ถามเรื่องเปิด PR · แผนผลิตรายเดือน/รายสัปดาห์ · SKU เสี่ยงของขาด — "
                           "ตัวเลขคำนวณจากข้อมูลในชีต · AI: Google Gemini")

tab_ai, tab_plan = st.tabs(["💬 ถาม AI", "📅 แผนผลิตรายเดือน / รายสัปดาห์"])


def _secret(name, default=None):
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:
        return os.environ.get(name, default)


def _err_text(e: Exception) -> str:
    s = str(e)
    if "429" in s or "RESOURCE_EXHAUSTED" in s:
        return "ใช้ครบโควตาฟรีของ Gemini ในช่วงนี้แล้ว — รอสักครู่แล้วลองใหม่ หรือเปลี่ยนรุ่นเป็น Flash-Lite ใน Secrets (GEMINI_MODEL)"
    if "API key" in s or "API_KEY" in s or "401" in s or "403" in s:
        return "API key ไม่ถูกต้องหรือไม่มีสิทธิ์ — ตรวจ GEMINI_API_KEY ใน Secrets"
    if "404" in s or "not found" in s.lower():
        return f"ไม่พบรุ่นโมเดลนี้ — ตั้ง GEMINI_MODEL ใน Secrets ให้ตรงกับรุ่นที่มีใน Google AI Studio ({s[:120]})"
    return f"เกิดข้อผิดพลาด: {s[:300]}"


def _show_tables(tables, key_prefix):
    for i, (title, df) in enumerate(tables):
        with st.expander(f"📋 {title} ({len(df):,} แถว)", expanded=len(tables) == 1 and len(df) <= 15):
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button("⬇️ ดาวน์โหลด (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{title}.csv", mime="text/csv", key=f"{key_prefix}_{i}")


# ============================================================ ถาม AI
with tab_ai:
    api_key = _secret("GEMINI_API_KEY")
    model_name = _secret("GEMINI_MODEL", "gemini-flash-latest")
    if not api_key:
        with st.container(border=True):
            ui.card_title("🔑 ตั้งค่า Gemini API key ก่อนใช้งาน")
            st.markdown("""
1. เข้า **aistudio.google.com** → *Get API key* → สร้าง key (ฟรี)
2. Streamlit Cloud: *Manage app → Settings → Secrets* ใส่
```toml
GEMINI_API_KEY = "ใส่ key ที่ได้"
GEMINI_MODEL = "gemini-flash-latest"   # ไม่ใส่ก็ได้
```
3. บันทึก แล้วรีเฟรชหน้านี้
""")
            api_key = st.text_input("หรือวาง key ชั่วคราวเพื่อทดลอง (ไม่ถูกบันทึก)", type="password")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        genai = None
        st.error("ยังไม่ได้ติดตั้ง google-genai — เพิ่ม `google-genai` ใน requirements.txt แล้ว Reboot app")

    if api_key and genai is not None:
        st.session_state.setdefault("ai_msgs", [])
        st.session_state.setdefault("ai_sink", [])
        loaded = st.session_state["ctx"]["loaded_at"]
        sig = hashlib.sha1(f"{api_key}|{model_name}|{loaded}".encode()).hexdigest()
        if st.session_state.get("ai_sig") != sig:
            sink = st.session_state["ai_sink"]
            client = genai.Client(api_key=api_key)
            st.session_state["ai_chat"] = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=ai_tools.system_prompt(model),
                    tools=ai_tools.make_tools(model, sink),
                    temperature=0.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=8),
                ))
            st.session_state["ai_sig"] = sig

        c1, c2 = st.columns([5, 1])
        c1.caption(f"รุ่นโมเดล: `{model_name}` · ส่งให้ AI เฉพาะตัวเลขสรุปของ SKU ที่ถาม (ไม่มีรายบิล/ลูกค้า/ราคาทุน) · "
                   "แพ็กเกจฟรีของ Gemini: Google อาจนำคำถาม-คำตอบไปใช้พัฒนาบริการ")
        if c2.button("🗑️ ล้างแชท", use_container_width=True):
            for k in ("ai_msgs", "ai_sig", "ai_chat"):
                st.session_state.pop(k, None)
            st.session_state["ai_sink"] = []
            st.rerun()

        examples = ["101-CS090-200R เหลือ 300 ม้วน ต้องเปิด PR ไหม",
                    f"ขอแผนผลิต{dp.month_label(dp.default_plan_month(model))} กลุ่ม AX, AY แบ่งรายสัปดาห์",
                    "SKU กลุ่ม AX AY BX ตัวไหนเสี่ยงของขาดบ้าง"]
        pending = None
        if not st.session_state["ai_msgs"]:
            st.markdown("**ลองถาม:**")
            cols = st.columns(len(examples))
            for col, ex in zip(cols, examples):
                if col.button(ex, use_container_width=True):
                    pending = ex

        for i, msg in enumerate(st.session_state["ai_msgs"]):
            with st.chat_message(msg["role"], avatar="🧑‍💼" if msg["role"] == "user" else "🤖"):
                st.markdown(msg["text"])
                if msg.get("tables"):
                    _show_tables(msg["tables"], f"hist{i}")

        prompt = st.chat_input("ถามเรื่อง PR / แผนผลิต / ของขาด เช่น 'สาย CAT5E สีขาว เหลือ 50 ต้องผลิตเพิ่มไหม'") or pending
        if prompt:
            st.session_state["ai_msgs"].append({"role": "user", "text": prompt})
            with st.chat_message("user", avatar="🧑‍💼"):
                st.markdown(prompt)
            with st.chat_message("assistant", avatar="🤖"):
                n0 = len(st.session_state["ai_sink"])
                with st.spinner("กำลังคำนวณ…"):
                    try:
                        resp = st.session_state["ai_chat"].send_message(prompt)
                        text = resp.text or "(ไม่มีคำตอบ)"
                    except Exception as e:  # noqa: BLE001
                        text = "⚠️ " + _err_text(e)
                tables = st.session_state["ai_sink"][n0:]
                st.markdown(text)
                _show_tables(tables, f"new{len(st.session_state['ai_msgs'])}")
            st.session_state["ai_msgs"].append({"role": "assistant", "text": text, "tables": tables})

# ============================================================ แผนผลิต (ไม่ใช้ AI)
with tab_plan:
    months = sorted(set([dp.default_plan_month(model)] + [mk for mk in model.fc_months if mk > model.last_month]))
    c1, c2 = st.columns([2, 3])
    mo = c1.selectbox("เดือนที่วางแผน", months, format_func=dp.month_label)
    only_fc = c2.radio("SKU ที่รวมในแผน", ["เฉพาะที่มี Forecast", "ทุก SKU ตามตัวกรอง (ไม่มี FC ใช้ค่าเฉลี่ย)"],
                       horizontal=True)
    sku_list = None if only_fc.startswith("เฉพาะ") else sorted(skus)
    plan = dp.production_plan(model, mo, sku_list)
    plan = plan[plan["sku"].isin(skus)] if len(plan) else plan
    if plan.empty:
        st.info("ไม่มี SKU ตามเงื่อนไข")
    else:
        plan = plan.sort_values("plan_qty", ascending=False)
        wcols = [c for c in plan.columns if c.startswith("W")]
        c = st.columns(4)
        ui.kpi(c[0], "แผนผลิตรวม", ui.fmt_num(plan["plan_qty"].sum()), f"{dp.month_label(mo)} · หน่วย", ui.BLUE, "🏭")
        ui.kpi(c[1], "จำนวน SKU", f"{(plan['plan_qty'] > 0).sum():,}", f"จาก {len(plan):,} SKU", ui.TEAL, "📦")
        ui.kpi(c[2], "ใช้ Forecast", f"{(plan['demand_basis'] == 'Forecast').sum():,} SKU",
               f"ค่าเฉลี่ยในอดีต {(plan['demand_basis'] != 'Forecast').sum():,} SKU", ui.ORANGE, "🎯")
        busiest = plan[wcols].sum().idxmax()
        ui.kpi(c[3], "สัปดาห์ที่ผลิตมากสุด", busiest.split(" ")[0], busiest.split(" ", 1)[1].strip("()"), ui.PURPLE, "📅")

        with st.container(border=True):
            ui.card_title("แผนผลิตรายสัปดาห์ (แบ่งตามสัดส่วนยอดขายในอดีต)")
            wt = plan[wcols].sum()
            fig = go.Figure(go.Bar(x=wt.index, y=wt.values, marker_color=ui.SERIES[:len(wt)],
                                   text=[f"{v:,.0f}" for v in wt.values], textposition="outside"))
            fig.update_yaxes(tickformat=",.0f")
            st.plotly_chart(ui.style(fig, 320, legend=False), use_container_width=True)
            st.caption("สัดส่วนคิดจากยอดขาย 12 เดือนล่าสุดของแต่ละ SKU ตามช่วงวันที่ในเดือน "
                       "(SKU ที่มีประวัติน้อยกว่า 3 เดือน ใช้สัดส่วนของหมวด) · แผนนี้ยังไม่หักสต๊อกคงเหลือ")

        cols = ["sku", "name", "category", "ABC_XYZ", "priority_tier", "demand_basis", "plan_qty", *wcols,
                "safety_stock", "week_source", "note"]
        st.dataframe(plan[cols], hide_index=True, use_container_width=True, height=480, column_config={
            **ui.SKU_COLS, "category": "หมวด", "demand_basis": "ความต้องการจาก",
            "plan_qty": ui.num("แผนผลิต (หน่วย)"), "safety_stock": ui.num("SS"),
            "week_source": "สัดส่วนสัปดาห์จาก", "note": "หมายเหตุ", **{w: ui.num(w) for w in wcols}})
        st.download_button("⬇️ ดาวน์โหลดแผนผลิต (CSV)", plan[cols].to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"production_plan_{mo}.csv", mime="text/csv")
