import functools
import hashlib
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_tools
import dp_core as dp
import ui

model, flt, skus = ui.ctx()
ui.header("ผู้ช่วยวางแผน", "ถามเรื่องเปิด PR · แผนผลิตรายเดือน/รายสัปดาห์ · SKU เสี่ยงของขาด — "
                           "ตัวเลขคำนวณจากข้อมูลในชีต · AI: Google Gemini")

# สต๊อกคงเหลือที่ผู้ใช้กรอก {sku: (on_hand, on_order)} — ใช้ dict เดิมตลอด AI จะเห็นค่าล่าสุด
STOCK = st.session_state.setdefault("stock", {})

tab_ai, tab_plan = st.tabs(["💬 ถาม AI", "📅 แผนผลิตรายเดือน / รายสัปดาห์"])


def _secret(name, default=None):
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:
        return os.environ.get(name, default)


def _err_text(e: Exception) -> str:
    s = str(e)
    if "503" in s or "UNAVAILABLE" in s:
        return "เซิร์ฟเวอร์ Gemini มีคนใช้เยอะ (ลองรุ่นสำรองแล้วก็ยังไม่ว่าง) — รอ 1–2 นาทีแล้วถามใหม่ · คำถาม PR / แผนผลิต / ของขาด ที่ระบุรหัสหรือกลุ่ม ใช้โหมดเร็วได้โดยไม่ต้องรอ AI"
    if "429" in s or "RESOURCE_EXHAUSTED" in s:
        return "ใช้ครบโควตาฟรีของ Gemini ในช่วงนี้แล้ว — รอสักครู่แล้วลองใหม่ หรือเปลี่ยนรุ่นเป็น Flash-Lite ใน Secrets (GEMINI_MODEL)"
    if "API key" in s or "API_KEY" in s or "401" in s or "403" in s:
        return "API key ไม่ถูกต้องหรือไม่มีสิทธิ์ — ตรวจ GEMINI_API_KEY ใน Secrets"
    if "404" in s or "not found" in s.lower():
        return f"ไม่พบรุ่นโมเดลนี้ — ตั้ง GEMINI_MODEL ใน Secrets ให้ตรงกับรุ่นที่มีใน Google AI Studio ({s[:120]})"
    return f"เกิดข้อผิดพลาด: {s[:300]}"


ASSISTANT_VERSION = "1.5"
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.7-flash-lite", "gemini-3.5-flash-lite",
                   "gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


def _pick_model(client, exclude=None):
    """หารุ่น Gemini Flash ที่ key นี้เรียกได้ (generateContent) — เลือกรุ่นใหม่สุดที่ไม่ใช่ preview/lite"""
    import re
    try:
        names = []
        for m in client.models.list():
            acts = getattr(m, "supported_actions", None) or []
            name = (m.name or "").replace("models/", "")
            if "generateContent" in acts and name != exclude:
                names.append(name)
    except Exception:  # noqa: BLE001
        return None
    bad = ("image", "tts", "audio", "live", "embedding", "vision", "thinking", "exp", "computer", "robotics")
    cands = [n for n in names if "flash" in n and n.startswith("gemini") and not any(b in n for b in bad)]
    if not cands:
        return None

    def rank(n):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return ("preview" not in n, "lite" not in n, float(v.group(1)) if v else 0, n.endswith("latest"))
    return max(cands, key=rank)


def _timed(fn):
    """บันทึกว่า AI เรียกเครื่องมือไหน ใช้เวลาเท่าไร (ไว้แสดงใต้คำตอบ)"""
    @functools.wraps(fn)
    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            st.session_state.setdefault("ai_calls", []).append((fn.__name__, time.perf_counter() - t))
    return wrap


def _thinking(model_name):
    """ลดการ 'คิด' ของโมเดล — งานนี้ตัวเลขมาจากเครื่องมือ ไม่ต้องคิดลึก ตอบเร็วขึ้นมาก"""
    try:
        from google.genai import types
        if "gemini-3" in model_name:
            return {"thinking_config": types.ThinkingConfig(thinking_level="low")}
        if "gemini-2.5-flash" in model_name:
            return {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
    except Exception:  # noqa: BLE001  (SDK รุ่นเก่าไม่มีพารามิเตอร์นี้)
        pass
    return {}


def _show_tables(tables, key_prefix):
    for i, (title, df) in enumerate(tables):
        with st.expander(f"📋 {title} ({len(df):,} แถว)", expanded=len(tables) == 1 and len(df) <= 15):
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button("⬇️ ดาวน์โหลด (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{title}.csv", mime="text/csv", key=f"{key_prefix}_{i}")


# ============================================================ ถาม AI
with tab_ai:
    api_key = _secret("GEMINI_API_KEY")
    model_name = _secret("GEMINI_MODEL", FALLBACK_MODELS[0])
    if not api_key:
        with st.container(border=True):
            ui.card_title("🔑 ตั้งค่า Gemini API key ก่อนใช้งาน")
            st.markdown("""
1. เข้า **aistudio.google.com** → *Get API key* → สร้าง key (ฟรี)
2. Streamlit Cloud: *Manage app → Settings → Secrets* ใส่
```toml
GEMINI_API_KEY = "ใส่ key ที่ได้"
GEMINI_MODEL = "gemini-3.7-flash"   # ไม่ใส่ก็ได้
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
        mkey = hashlib.sha1(f"{api_key}|{model_name}".encode()).hexdigest()   # จำรุ่นที่ใช้ได้ ข้ามการรีเฟรชข้อมูล

        def _new_chat(use_model):
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta"))
            st.session_state["ai_client"] = client   # ต้องเก็บไว้ ไม่งั้น client ถูกปิดตอนรันรอบถัดไป
            st.session_state["ai_chat"] = client.chats.create(
                model=use_model,
                config=types.GenerateContentConfig(
                    system_instruction=ai_tools.system_prompt(model),
                    tools=[_timed(f) for f in ai_tools.make_tools(model, st.session_state["ai_sink"], STOCK)],
                    temperature=0.2,
                    **_thinking(use_model),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=8),
                ))
            st.session_state["ai_model"] = use_model

        def _send_with_fallback(prompt):
            """ส่งคำถาม · รุ่นไม่มี (404) / คนใช้เยอะ (503) / โควตาเต็ม (429) → เปลี่ยนไปรุ่นถัดไปเอง"""
            try:
                return st.session_state["ai_chat"].send_message(prompt)
            except Exception as e1:  # noqa: BLE001
                msg = str(e1)
                if "closed" in msg:
                    _new_chat(st.session_state["ai_model"])
                    return st.session_state["ai_chat"].send_message(prompt)
                if not any(k in msg for k in ("404", "not found", "NOT_FOUND", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
                    raise
                tried = [st.session_state["ai_model"]]
                listed = None
                if "404" in msg or "not found" in msg.lower():
                    listed = _pick_model(genai.Client(api_key=api_key, http_options=types.HttpOptions(api_version="v1beta")),
                                         exclude=tried[0])
                last = e1
                for alt in [m for m in [listed, *FALLBACK_MODELS] if m and m not in tried]:
                    tried.append(alt)
                    try:
                        _new_chat(alt)
                        resp = st.session_state["ai_chat"].send_message(prompt)
                        st.session_state.setdefault("ai_model_ok", {})[mkey] = alt
                        return resp
                    except Exception as e2:  # noqa: BLE001
                        last = e2
                        if not any(k in str(e2) for k in ("404", "not found", "NOT_FOUND", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
                            raise
                raise RuntimeError(f"ลองแล้ว {', '.join(tried)} — {last}")

        if st.session_state.get("ai_sig") != sig:
            _new_chat(st.session_state.get("ai_model_ok", {}).get(mkey) or model_name)
            st.session_state["ai_sig"] = sig

        c1, c2 = st.columns([5, 1])
        n_stock = sum(v[0] is not None for v in STOCK.values())
        c1.caption(f"ผู้ช่วย v{ASSISTANT_VERSION} · รุ่นโมเดล: `{st.session_state.get('ai_model', model_name)}` · สต๊อกที่กรอกไว้: {n_stock:,} SKU (กรอกในแท็บแผนผลิต) · ส่งให้ AI เฉพาะตัวเลขสรุปของ SKU ที่ถาม (ไม่มีรายบิล/ลูกค้า/ราคาทุน) · "
                   "แพ็กเกจฟรีของ Gemini: Google อาจนำคำถาม-คำตอบไปใช้พัฒนาบริการ")
        c2.toggle("⚡ โหมดเร็ว", value=True, key="ai_fast",
                  help="คำถามมาตรฐาน (PR ที่มีรหัส, แผนผลิต, ของขาด) คำนวณตอบทันทีโดยไม่ต้องรอ Gemini · คำถามอื่นส่งให้ AI")
        if c2.button("🗑️ ล้างแชท", use_container_width=True):
            for k in ("ai_msgs", "ai_sig", "ai_chat", "ai_client"):
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
                if msg.get("meta"):
                    st.caption(msg["meta"])
                if msg.get("tables"):
                    _show_tables(msg["tables"], f"hist{i}")

        prompt = st.chat_input("ถามเรื่อง PR / แผนผลิต / ของขาด เช่น 'สาย CAT5E สีขาว เหลือ 50 ต้องผลิตเพิ่มไหม'") or pending
        if prompt:
            st.session_state["ai_msgs"].append({"role": "user", "text": prompt})
            with st.chat_message("user", avatar="🧑‍💼"):
                st.markdown(prompt)
            with st.chat_message("assistant", avatar="🤖"):
                n0 = len(st.session_state["ai_sink"])
                st.session_state["ai_calls"] = []
                meta = ""
                t0 = time.perf_counter()
                quick = None
                if st.session_state.get("ai_fast", True):
                    try:
                        quick = ai_tools.quick_answer(prompt, model, st.session_state["ai_sink"], STOCK)
                    except Exception:  # noqa: BLE001  ถ้าโหมดเร็วพัง ส่งให้ Gemini แทน
                        quick = None
                if quick:
                    text = quick
                    meta = f"⚡ โหมดเร็ว (คำนวณตรงจากสูตร ไม่ใช้ AI) · {time.perf_counter() - t0:.2f} วินาที"
                else:
                    with st.spinner("กำลังถาม Gemini…"):
                        try:
                            resp = _send_with_fallback(prompt)
                            text = resp.text or "(ไม่มีคำตอบ)"
                            calls = st.session_state.get("ai_calls", [])
                            tt = time.perf_counter() - t0
                            meta = (f"⏱️ {tt:.1f} วินาที · {st.session_state.get('ai_model')} · "
                                    f"เครื่องมือ: {', '.join(n for n, _ in calls) or '-'} "
                                    f"(คำนวณ {sum(d for _, d in calls):.2f} วิ ที่เหลือคือรอ Gemini)")
                        except Exception as e:  # noqa: BLE001
                            text = "⚠️ " + _err_text(e)
                            if "closed" in str(e):          # สร้าง client ใหม่ในรอบถัดไป
                                st.session_state.pop("ai_sig", None)
                tables = st.session_state["ai_sink"][n0:]
                st.markdown(text)
                if meta:
                    st.caption(meta)
                _show_tables(tables, f"new{len(st.session_state['ai_msgs'])}")
            st.session_state["ai_msgs"].append({"role": "assistant", "text": text, "tables": tables, "meta": meta})

# ============================================================ แผนผลิต (ไม่ใช้ AI)
with tab_plan:
    months = sorted(set([dp.default_plan_month(model)] + [mk for mk in model.fc_months if mk > model.last_month]))
    c1, c2 = st.columns([2, 3])
    mo = c1.selectbox("เดือนที่วางแผน", months, format_func=dp.month_label)
    only_fc = c2.radio("SKU ที่รวมในแผน", ["เฉพาะที่มี Forecast", "ทุก SKU ตามตัวกรอง (ไม่มี FC ใช้ค่าเฉลี่ย)"],
                       horizontal=True)
    sku_list = None if only_fc.startswith("เฉพาะ") else sorted(skus)

    with st.expander(f"📦 สต๊อกคงเหลือปัจจุบัน (ไม่บังคับ) — กรอกแล้ว {sum(v[0] is not None for v in STOCK.values()):,} SKU",
                     expanded=False):
        st.caption("กรอกเฉพาะ SKU ที่รู้ยอด · SKU ที่กรอก: แผนผลิต = ความต้องการ + SS − คงเหลือ − ค้างรับ · "
                   "ที่ไม่กรอก: แผน = ความต้องการ (ยังไม่หักสต๊อก) · ผู้ช่วย AI ใช้ตัวเลขชุดนี้ด้วย · "
                   "ค่าจะหายเมื่อปิดเบราว์เซอร์ — เก็บถาวรได้ด้วยไฟล์ CSV")
        up = st.file_uploader("อัปโหลดไฟล์สต๊อก (CSV/Excel คอลัมน์: sku, on_hand, on_order)", type=["csv", "xlsx"])
        if up is not None and st.session_state.get("stock_file") != (up.name, up.size):
            f = pd.read_csv(up) if up.name.endswith(".csv") else pd.read_excel(up)
            f.columns = [str(c).strip().lower() for c in f.columns]
            if {"sku", "on_hand"} <= set(f.columns):
                for r in f.itertuples():
                    oh = pd.to_numeric(r.on_hand, errors="coerce")
                    oo = pd.to_numeric(getattr(r, "on_order", None), errors="coerce")
                    STOCK[str(r.sku).strip()] = (None if pd.isna(oh) else float(oh), None if pd.isna(oo) else float(oo))
                st.session_state["stock_file"] = (up.name, up.size)
                st.session_state["stock_ver"] = st.session_state.get("stock_ver", 0) + 1
            else:
                st.error("ไฟล์ต้องมีคอลัมน์ sku และ on_hand")
        base = (model.master.drop_duplicates("sku").set_index("sku")
                .loc[lambda d: d.index.isin(skus), ["name", "ABC_XYZ"]].sort_index())
        base["on_hand"] = [STOCK.get(k, (None, None))[0] for k in base.index]
        base["on_order"] = [STOCK.get(k, (None, None))[1] for k in base.index]
        base = base.reset_index()
        only_filled = st.toggle("แสดงเฉพาะที่กรอกแล้ว", value=False)
        view = base[base["on_hand"].notna()] if only_filled else base
        ed = st.data_editor(view, hide_index=True, use_container_width=True, height=320,
                            key=f"stock_ed_{st.session_state.get('stock_ver', 0)}_{only_filled}",
                            disabled=["sku", "name", "ABC_XYZ"], column_config={
                                **ui.SKU_COLS, "on_hand": ui.num("คงเหลือ"), "on_order": ui.num("ค้างรับ")})
        for r in ed.itertuples():
            oh = None if pd.isna(r.on_hand) else float(r.on_hand)
            oo = None if pd.isna(r.on_order) else float(r.on_order)
            if oh is None and oo is None:
                STOCK.pop(r.sku, None)
            else:
                STOCK[r.sku] = (oh, oo)
        b1, b2 = st.columns(2)
        filled = base.assign(on_hand=[STOCK.get(k, (None, None))[0] for k in base["sku"]],
                             on_order=[STOCK.get(k, (None, None))[1] for k in base["sku"]])
        b1.download_button("⬇️ เก็บสต๊อกที่กรอกเป็น CSV", filled[filled["on_hand"].notna()][["sku", "on_hand", "on_order"]]
                           .to_csv(index=False).encode("utf-8-sig"), file_name="stock_on_hand.csv", mime="text/csv",
                           use_container_width=True)
        if b2.button("ล้างสต๊อกทั้งหมด", use_container_width=True):
            STOCK.clear()
            st.session_state["stock_ver"] = st.session_state.get("stock_ver", 0) + 1
            st.rerun()

    on_hand = {k: v[0] for k, v in STOCK.items() if v[0] is not None}
    on_order = {k: v[1] for k, v in STOCK.items() if v[1] is not None}
    plan = dp.production_plan(model, mo, sku_list, on_hand=on_hand, on_order=on_order)
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
            n_ded = int(plan["on_hand"].notna().sum())
            st.caption("สัดส่วนคิดจากยอดขาย 12 เดือนล่าสุดของแต่ละ SKU ตามช่วงวันที่ในเดือน "
                       "(SKU ที่มีประวัติน้อยกว่า 3 เดือน ใช้สัดส่วนของหมวด) · "
                       + (f"หักสต๊อกคงเหลือแล้ว {n_ded:,} SKU · ที่เหลือยังไม่หักสต๊อก" if n_ded
                          else "ยังไม่หักสต๊อกคงเหลือ — กรอกได้ในช่อง 📦 ด้านบน"))

        cols = ["sku", "name", "category", "ABC_XYZ", "priority_tier", "demand_basis", "demand", "safety_stock",
                "on_hand", "on_order", "plan_qty", *wcols, "week_source", "note"]
        st.dataframe(plan[cols], hide_index=True, use_container_width=True, height=480, column_config={
            **ui.SKU_COLS, "category": "หมวด", "demand_basis": "ความต้องการจาก",
            "plan_qty": ui.num("แผนผลิต (หน่วย)"), "safety_stock": ui.num("SS"), "demand": ui.num("ความต้องการ"),
            "on_hand": ui.num("คงเหลือ"), "on_order": ui.num("ค้างรับ"),
            "week_source": "สัดส่วนสัปดาห์จาก", "note": "หมายเหตุ", **{w: ui.num(w) for w in wcols}})
        st.download_button("⬇️ ดาวน์โหลดแผนผลิต (CSV)", plan[cols].to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"production_plan_{mo}.csv", mime="text/csv")
