"""
ai_tools.py — เครื่องมือที่ผู้ช่วย AI (Gemini) เรียกใช้ได้

หลักการ: AI ไม่คำนวณตัวเลขเอง ทุกตัวเลขมาจากฟังก์ชันใน dp_core
ข้อมูลที่ส่งกลับให้ AI เป็นผลสรุปของ SKU ที่ถามเท่านั้น (ไม่มีรายบิล / ลูกค้า / ราคาทุน)
"""

import re

import numpy as np
import pandas as pd

import dp_core as dp

TH_MONTH_ALIASES = {
    "ม.ค.": 1, "มกรา": 1, "ก.พ.": 2, "กุมภา": 2, "มี.ค.": 3, "มีนา": 3, "เม.ย.": 4, "เมษา": 4,
    "พ.ค.": 5, "พฤษภา": 5, "มิ.ย.": 6, "มิถุนา": 6, "ก.ค.": 7, "กรกฎา": 7, "ส.ค.": 8, "สิงหา": 8,
    "ก.ย.": 9, "กันยา": 9, "ต.ค.": 10, "ตุลา": 10, "พ.ย.": 11, "พฤศจิกา": 11, "ธ.ค.": 12, "ธันวา": 12,
}


def parse_month(text: str, model: dp.Model) -> int:
    """'2026-12' / '202612' / '12/2026' / 'ธ.ค.' / 'ธันวาคม 2569' / '' → 202612"""
    t = str(text or "").strip()
    if not t:
        return dp.default_plan_month(model)
    if m := re.fullmatch(r"(\d{4})-?(\d{1,2})", t):
        y, mo = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[/-](\d{4})", t):
        y, mo = int(m.group(2)), int(m.group(1))
    else:
        mo = next((v for k, v in TH_MONTH_ALIASES.items() if k in t), None)
        if mo is None:
            return dp.default_plan_month(model)
        yy = re.search(r"(\d{4}|\d{2})", t)
        if yy:
            y = int(yy.group(1))
            if y < 100:           # 26 → 2026 (ค.ศ.) · 69 → 2569 (พ.ศ.)
                y = y + 2500 if y >= 60 else y + 2000
        else:      # ไม่ระบุปี → เดือนนั้นที่อยู่ถัดจากข้อมูลล่าสุด
            base = model.last_month
            y = base // 100 + (1 if mo <= base % 100 else 0)
    if y > 2400:
        y -= 543
    return y * 100 + mo


def _split(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\s;]+", str(text or "")) if x.strip()]


def _num(v, d=1):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return None
    return round(float(v), d)


def _records(df: pd.DataFrame, cols: list[str], n: int) -> list[dict]:
    out = df[[c for c in cols if c in df]].head(n).copy()
    for c in out.columns:
        if out[c].dtype.kind == "f":
            out[c] = out[c].round(1)
    return out.replace({np.nan: None}).to_dict("records")


def make_tools(model: dp.Model, sink: list, stock: dict | None = None):
    """stock: {sku: (on_hand, on_order)} ที่ผู้ใช้กรอกในแท็บแผนผลิต — ใช้ dict เดิมเสมอเพื่อให้เห็นค่าล่าสุด"""
    stock = stock if stock is not None else {}
    """สร้างฟังก์ชันเครื่องมือ (ผูกกับข้อมูลชุดปัจจุบัน) — sink เก็บตารางเต็มไว้แสดงใต้คำตอบ"""
    m = model.master.drop_duplicates("sku").set_index("sku")

    def find_sku(keyword: str) -> dict:
        """ค้นหารหัสสินค้า (SKU) จากรหัสบางส่วนหรือชื่อสินค้า เช่น 'CAT5E', 'สายดร์อป', '101-CS090'
        ใช้เมื่อผู้ใช้พิมพ์ชื่อสินค้าหรือรหัสไม่ครบ ก่อนเรียกเครื่องมืออื่นที่ต้องใช้รหัสเต็ม"""
        k = str(keyword).strip().lower()
        hit = model.master[model.master["sku"].str.lower().str.contains(k, regex=False)
                           | model.master["name"].astype(str).str.lower().str.contains(k, regex=False)]
        hit = hit.sort_values("value_rank", na_position="last")
        return {"matches": len(hit),
                "items": _records(hit, ["sku", "name", "ABC_XYZ", "priority_tier", "mean_monthly_qty"], 15)}

    def sku_info(sku: str) -> dict:
        """ข้อมูลการวางแผนของ SKU หนึ่งตัว: กลุ่ม ABC-XYZ, tier, ยอดขายเฉลี่ย/เดือน, Safety stock, ROP,
        Target stock, Lead time, ยอดขายจริง 6 เดือนล่าสุด และ Forecast เดือนข้างหน้า (หน่วย: จำนวน)"""
        sku = sku.strip()
        if sku not in m.index:
            return {"error": f"ไม่พบรหัส {sku} — ลองใช้ find_sku"}
        s = m.loc[sku]
        hist = model.monthly[model.monthly["sku"] == sku].set_index("month")["qty"]
        last6 = dp.month_range(dp.month_add(model.last_month, -5), model.last_month)
        fc = model.fc[(model.fc["sku"] == sku) & (model.fc["month"] > model.last_month)]
        return {
            "sku": sku, "name": s.get("name"), "ABC_XYZ": s.get("ABC_XYZ"), "priority_tier": s.get("priority_tier"),
            "status": s.get("Status"), "production": s.get("Production"),
            "mean_monthly_qty": _num(s.get("mean_monthly_qty")), "cv": _num(s.get("cv"), 2),
            "safety_stock": _num(s.get("safety_stock"), 0), "reorder_point": _num(s.get("reorder_point"), 0),
            "target_stock": _num(s.get("target_stock"), 0), "lead_time_days": _num(s.get("lead_time_days"), 0),
            "sales_last_6_months": {dp.month_label(mo): float(hist.get(mo, 0)) for mo in last6},
            "forecast_next": {dp.month_label(r.month): float(r.forecast_qty) for r in fc.itertuples()},
        }

    def pr_suggestion(sku: str, on_hand: float = -1.0, on_order: float = -1.0, lot_size: float = 1.0,
                      review_months: float = 1.0) -> dict:
        """คำนวณว่าควรเปิด PR (ผลิต/สั่งซื้อ) หรือไม่ และจำนวนเท่าไร สำหรับ SKU หนึ่งตัว
        on_hand = สต๊อกคงเหลือปัจจุบัน ถ้าผู้ใช้ไม่บอกให้ส่ง -1 ระบบจะใช้ค่าจากตารางสต๊อกที่กรอกไว้ (ถ้ามี)
        ถ้าตอบกลับว่า need_on_hand ให้ถามผู้ใช้
        on_order = ของที่สั่ง/ผลิตค้างรับอยู่ (-1 = ใช้จากตาราง หรือ 0), lot_size = ปัดขึ้นทีละกี่หน่วย, review_months = รอบวางแผน (เดือน)"""
        sku = sku.strip()
        saved = stock.get(sku)
        stock_src = "ผู้ใช้บอกในแชท"
        if on_hand is None or on_hand < 0:
            if saved is None or saved[0] is None:
                return {"need_on_hand": True, "sku": sku,
                        "message": "ยังไม่มีสต๊อกคงเหลือของ SKU นี้ ให้ถามผู้ใช้ หรือให้กรอกในแท็บแผนผลิต"}
            on_hand, stock_src = saved[0], "ตารางสต๊อกที่กรอกไว้"
        if on_order is None or on_order < 0:
            on_order = (saved[1] if saved and saved[1] is not None else 0.0)
        rows = pd.DataFrame([{"sku": sku.strip(), "on_hand": on_hand, "on_order": on_order, "lot_size": lot_size}])
        res = dp.pr_calc(model, rows, review_months)
        if res.empty or "pr_qty" not in res:
            return {"error": f"ไม่พบรหัส {sku}"}
        sink.append((f"คำนวณ PR — {sku}", res))
        r = res.iloc[0]
        return {"stock_source": stock_src, **{k: (_num(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()
                if k in ("sku", "name", "ABC_XYZ", "on_hand", "on_order", "demand_month", "demand_basis",
                         "lead_time_days", "safety_stock", "rop", "target", "cover_months", "status", "pr_qty")}}

    def production_plan(month: str = "", skus: str = "", abc_xyz: str = "", tier: str = "",
                        category: str = "", stock_text: str = "", min_cover_days: float = 3.0,
                        weekly: bool = True, top_n: int = 25) -> dict:
        """แผนผลิตของเดือนที่ระบุ (หน่วย: จำนวน) เฉพาะ SKU ที่ผลิตเอง (Production = Y ในชีต Info) พร้อมแบ่งรายสัปดาห์ตามสัดส่วนยอดขายในอดีต
        month: เช่น '2026-12' หรือ 'ธ.ค.' (เว้นว่าง = เดือนถัดไป)
        skus: รหัสคั่นด้วยจุลภาค (เว้นว่าง = ทุก SKU ที่มี forecast เดือนนั้น)
        abc_xyz: กรองกลุ่ม เช่น 'AX,AY' · tier: เช่น 'A1-Core' · category: หมวด เช่น '1,3'
        stock_text: สต๊อกคงเหลือที่ผู้ใช้บอกในแชท รูปแบบ 'รหัส=จำนวน; รหัส=จำนวน' (เว้นว่างได้)
        SKU ที่มีสต๊อก (จากแชทหรือตารางที่กรอกไว้): Rolling plan — ยอดขาย/วัน = ความต้องการ ÷ วันในเดือน,
        ผลิตต้นสัปดาห์ให้สต๊อกปลายสัปดาห์พอขาย ≥ min_cover_days วัน (ค่าตั้งต้น 3), หมวดที่มีขั้นต่ำผลิต ≥ ขั้นต่ำ/รอบ
        SKU ที่ไม่มีสต๊อก: แผน = ความต้องการ (ยังไม่หักสต๊อก) — ดูคอลัมน์ note"""
        mo = parse_month(month, model)
        sku_list = _split(skus) or None
        oh = {k: v[0] for k, v in stock.items() if v[0] is not None}
        oo = {k: v[1] for k, v in stock.items() if v[1] is not None}
        for k, v in re.findall(r"([\w\-./]+)\s*=\s*([\d,]+(?:\.\d+)?)", str(stock_text or "")):
            oh[k.strip()] = float(v.replace(",", ""))
        df = dp.production_plan(model, mo, sku_list, on_hand=oh, on_order=oo, weekly=True,
                                min_cover_days=float(min_cover_days))
        if df.empty:
            return {"month": dp.month_label(mo), "error": "ไม่มี SKU ที่ตรงเงื่อนไข (ต้องเป็นสินค้าที่ผลิตเอง Production = Y) หรือยังไม่มี forecast เดือนนี้"}
        if abc_xyz:
            df = df[df["ABC_XYZ"].isin([x.upper() for x in _split(abc_xyz)])]
        if tier:
            df = df[df["priority_tier"].isin(_split(tier))]
        if category:
            df = df[df["category"].isin([float(x) for x in _split(category) if x.replace(".", "").isdigit()])]
        df = df.sort_values("plan_qty", ascending=False)
        sink.append((f"แผนผลิต {dp.month_label(mo)}", df))
        wcols = [c for c in df.columns if c.startswith("W")]
        return {
            "month": dp.month_label(mo), "n_sku": int(len(df)), "total_plan_qty": float(df["plan_qty"].sum()),
            "weekly_total": {c: int(df[c].sum()) for c in wcols},
            "n_sku_stock_deducted": int(df["on_hand"].notna().sum()),
            "week_split_method": "สัดส่วนยอดขาย 12 เดือนล่าสุดตามสัปดาห์ของเดือน (SKU → หมวด → ภาพรวม)",
            "rows_shown": min(top_n, len(df)),
            "min_batch_rule": "หมวดที่มีขั้นต่ำ (ค่าตั้งต้นหมวด 1 และ 3 = 100) สัปดาห์ที่น้อยกว่าขั้นต่ำถูกรวบไปผลิตพร้อมสัปดาห์ก่อนหน้า ทั้งเดือนไม่ถึงขั้นต่ำผลิตครั้งเดียว W1 · หมวดอื่นผลิตตามสัปดาห์",
            "n_sku_below_cover": int((df["cover_days_now"] < float(min_cover_days)).sum()),
            "items": _records(df, ["sku", "name", "category", "ABC_XYZ", "demand_basis", "demand", "daily_demand", "on_hand",
                                   "cover_days_now", "plan_qty", *wcols, "end_stock", "end_cover_days", "batch_note", "note"], top_n),
        }

    def stockout_watch(groups: str = "AX,AY,BX", threshold: float = 0.2, top_n: int = 20) -> dict:
        """รายการ SKU ที่เสี่ยงของขาด เพราะขายจริงเกิน forecast, forecast เดือนหน้าต่ำกว่ายอดขาย 3 เดือนล่าสุด,
        ไม่มี forecast หรือดีมานด์กำลังโต · groups = กลุ่ม ABC-XYZ คั่นด้วยจุลภาค · threshold = เกณฑ์ต่าง (0.2 = 20%)"""
        w = dp.stockout_watch(model, tuple(x.upper() for x in _split(groups)), float(threshold))
        risk = w[w["risk_score"] > 0]
        sink.append((f"เฝ้าระวังของขาด ({groups})", risk))
        return {"checked": int(len(w)), "at_risk": int(len(risk)), "next_month": w["next_month"].iloc[0] if len(w) else "-",
                "items": _records(risk, ["sku", "name", "ABC_XYZ", "risk_score", "recent3", "fc_next",
                                         "gap_next", "safety_stock", "risk_flags"], top_n)}

    return [find_sku, sku_info, pr_suggestion, production_plan, stockout_watch]


def system_prompt(model: dp.Model) -> str:
    nxt = dp.default_plan_month(model)
    return f"""คุณคือผู้ช่วยวางแผนการผลิต (Demand Planning) ของบริษัทผลิตและจำหน่ายสายไฟ/สายสัญญาณ ตอบเป็นภาษาไทย กระชับ เป็นมิตร

กฎสำคัญ:
1. ตัวเลขทุกตัวต้องมาจากเครื่องมือเท่านั้น ห้ามคำนวณหรือเดาตัวเลขเอง ถ้าเครื่องมือไม่มีข้อมูล ให้บอกตรง ๆ
2. หน่วยเป็น "จำนวน" (ม้วน/ชิ้นตามสินค้า) ไม่ใช่บาท
3. ถ้าผู้ใช้พิมพ์ชื่อสินค้าหรือรหัสไม่ครบ ใช้ find_sku ก่อน ถ้าเจอหลายตัวให้ถามว่าหมายถึงตัวไหน
   ถ้าให้รหัสครบแล้ว เรียกเครื่องมือหลัก (pr_suggestion / production_plan / stockout_watch) ได้ทันที ไม่ต้องเรียก find_sku หรือ sku_info ก่อน — เรียกเครื่องมือให้น้อยครั้งที่สุด
4. การคำนวณ PR ต้องรู้สต๊อกคงเหลือ: ถ้าผู้ใช้ไม่บอก ให้เรียก pr_suggestion ด้วย on_hand=-1 ก่อน (ระบบจะใช้ตารางสต๊อกที่ผู้ใช้กรอกไว้) ถ้าได้ need_on_hand ค่อยถามผู้ใช้
4.1 แผนผลิต: SKU ที่มีสต๊อกใช้ Rolling plan (ยอดขาย/วัน = ความต้องการ ÷ วันในเดือน · cover day = สต๊อก ÷ ยอดขาย/วัน · ผลิตต้นสัปดาห์ให้สต๊อกปลายสัปดาห์ ≥ 3 cover day) ที่ไม่มีสต๊อกคือยอดตามความต้องการ ยังไม่หักสต๊อก — บอกผู้ใช้ทุกครั้งว่ากี่ SKU ใช้ rolling และกี่ SKU ต่ำกว่า 3 วันแล้ว (ต้องผลิตด่วน)
5. แผนผลิตมีเฉพาะสินค้าที่ผลิตเอง (Production = Y) สินค้าซื้อมาขายไม่อยู่ในแผน ถ้าผู้ใช้ถามถึงสินค้าที่ไม่อยู่ในแผน ให้บอกเหตุผลนี้ (ใช้ pr_suggestion ได้ถ้าต้องการสั่งซื้อ)
5.2 แผนรายสัปดาห์ถูกรวบตามขั้นต่ำการผลิต (min_batch_rule) อธิบายให้ผู้ใช้เมื่อเกี่ยวข้อง
5.1 แผนผลิตรายสัปดาห์แบ่งตามสัดส่วนยอดขายในอดีตของแต่ละสัปดาห์ในเดือน (W1 = วันที่ 1–7 ... W5 = 29–สิ้นเดือน) บอกผู้ใช้ด้วย
6. บอกเสมอว่าความต้องการมาจาก Forecast หรือค่าเฉลี่ยในอดีต
7. สรุปตัวเลขสำคัญในคำตอบ ตารางเต็มระบบจะแสดงใต้คำตอบเอง ไม่ต้องพิมพ์ตารางยาวซ้ำ (แสดงไม่เกิน 10 แถว)
8. ตอบเฉพาะเรื่องการวางแผนผลิต/สต๊อก/ยอดขายของบริษัท

บริบท: ข้อมูลยอดขาย (บิล NV/IV) ถึง {model.last_date:%d/%m/%Y} · เดือนที่วางแผนถัดไป = {dp.month_label(nxt)} ·
มี forecast เดือน {', '.join(dp.month_label(x) for x in model.fc_months)}"""


# ---------------------------------------------------------------- โหมดเร็ว (ไม่ใช้ AI)
_SKU_RE = re.compile(r"\b\d{3}-[A-Za-z0-9][A-Za-z0-9\-]*")
_NUM = r"([\d,]+(?:\.\d+)?)"


def _f(v, d=0):
    return "-" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:,.{d}f}"


def quick_answer(text: str, model: dp.Model, sink: list, stock: dict | None = None):
    """ตอบคำถามมาตรฐาน 3 แบบทันทีด้วยสูตร (ไม่ต้องรอ Gemini) — ถ้าไม่เข้าแบบไหนคืน None"""
    t = str(text or "")
    tools = {f.__name__: f for f in make_tools(model, sink, stock)}
    known = set(model.master["sku"])
    skus = [s for s in dict.fromkeys(x.upper() for x in _SKU_RE.findall(t)) if s in known]
    groups = list(dict.fromkeys(g.upper() for g in re.findall(r"(?<![A-Za-z])([ABCabc][XYZNxyzn])(?![A-Za-z])", t)))

    def grab(pat):
        m = re.search(pat + r"\s*" + _NUM, t, re.I)
        return float(m.group(1).replace(",", "")) if m else None

    # 1) PR — มีรหัส 1 ตัว + คำถามเรื่องเปิด PR/สั่ง/ผลิตเพิ่ม/คงเหลือ
    if len(skus) == 1 and re.search(r"PR|เปิด|สั่ง|ผลิตเพิ่ม|เหลือ|สต๊อก|สต็อก|คงคลัง", t, re.I) and "แผน" not in t:
        oh = grab(r"(?:คงเหลือ|เหลือ|สต๊อก|สต็อก|มีอยู่|on.?hand)")
        oo = grab(r"(?:ค้างรับ|ค้างส่ง|on.?order)")
        lot = grab(r"(?:lot|ล็อต|ลอต)")
        r = tools["pr_suggestion"](skus[0], -1.0 if oh is None else oh, -1.0 if oo is None else oo, lot or 1.0)
        if r.get("need_on_hand"):
            return (f"**{skus[0]}** — บอกสต๊อกคงเหลือปัจจุบันด้วยนะคะ เช่น \"{skus[0]} เหลือ 300\" "
                    "(หรือกรอกไว้ในแท็บ 📅 แผนผลิต → 📦 สต๊อกคงเหลือ)")
        if "error" in r:
            return r["error"]
        go = (r.get("pr_qty") or 0) > 0
        return (f"**{r['sku']}** {r.get('name') or ''} ({r.get('ABC_XYZ')})\n\n"
                f"{'✅ **ควรเปิด PR ' + _f(r['pr_qty']) + ' หน่วย**' if go else '⏸️ **ยังไม่ต้องเปิด PR**'} — {r.get('status')}\n\n"
                f"- คงเหลือ {_f(r.get('on_hand'))} + ค้างรับ {_f(r.get('on_order'))} ({r.get('stock_source')}) "
                f"→ พอใช้ประมาณ {_f(r.get('cover_months'), 1)} เดือน\n"
                f"- ความต้องการ ~{_f(r.get('demand_month'))}/เดือน (จาก {r.get('demand_basis')}) · Lead time {_f(r.get('lead_time_days'))} วัน\n"
                f"- Safety stock {_f(r.get('safety_stock'))} · ROP {_f(r.get('rop'))} · Target {_f(r.get('target'))}\n"
                f"- PR = Target − (คงเหลือ + ค้างรับ) เมื่อของถึงจุดสั่ง (≤ ROP)")

    # 2) แผนผลิต
    if "แผน" in t:
        mtxt = ""
        if m := re.search(r"(\d{4}-\d{1,2}|\d{1,2}/\d{4})", t):
            mtxt = m.group(1)
        else:
            for k in sorted(TH_MONTH_ALIASES, key=len, reverse=True):
                if k in t:
                    yy = re.search(re.escape(k) + r"\S*\s*(\d{4}|\d{2})\b", t)
                    mtxt = k + (" " + yy.group(1) if yy else "")
                    break
        st_txt = "; ".join(f"{k}={v}" for k, v in re.findall(r"(\d{3}-[A-Za-z0-9\-]+)\s*(?:เหลือ|คงเหลือ)\s*" + _NUM, t))
        r = tools["production_plan"](month=mtxt, skus=",".join(skus) if skus and not st_txt else "",
                                     abc_xyz=",".join(groups), stock_text=st_txt)
        if "error" in r:
            return f"แผน {r['month']}: {r['error']}"
        wk = "\n".join(f"| {k} | {v:,} |" for k, v in r["weekly_total"].items())
        ded = r.get("n_sku_stock_deducted", 0)
        top = "\n".join(f"| {i['sku']} | {i.get('ABC_XYZ') or ''} | {_f(i.get('on_hand'))} | {_f(i.get('cover_days_now'), 1)} | "
                        f"{_f(i['plan_qty'])} | {i.get('batch_note') or ''} |" for i in r["items"][:10])
        return (f"**แผนผลิต {r['month']}**{' กลุ่ม ' + ', '.join(groups) if groups else ''} — "
                f"{r['n_sku']:,} SKU (เฉพาะสินค้าผลิตเอง Production = Y) รวม **{_f(r['total_plan_qty'])} หน่วย**\n\n"
                f"| สัปดาห์ | จำนวน |\n|---|---:|\n{wk}\n\n"
                f"แบ่งรายสัปดาห์ตามสัดส่วนยอดขาย 12 เดือนล่าสุดของแต่ละ SKU (ประวัติน้อย → ใช้ของหมวด) · "
                f"หมวดที่มีขั้นต่ำ ({', '.join(f'หมวด {k} = {v:,.0f}' for k, v in sorted(dp.min_batch_map(model).items()))}) "
                f"สัปดาห์ที่ไม่ถึงขั้นต่ำรวบไปผลิตพร้อมสัปดาห์ก่อนหน้า · "
                + (f"Rolling plan จากสต๊อก {ded:,} SKU (ปลายสัปดาห์พอขาย ≥ 3 วัน"
                   + (f" · ⚠️ ต่ำกว่า 3 วันแล้ว {r['n_sku_below_cover']:,} SKU" if r.get('n_sku_below_cover') else "")
                   + ") ที่เหลือยังไม่หักสต๊อก" if ded else
                   "ยังไม่หักสต๊อกคงเหลือ (กรอกได้ในแท็บ 📅 แผนผลิต)")
                + f"\n\n**10 อันดับแรก**\n\n| รหัส | กลุ่ม | คงเหลือ | พอขาย (วัน) | แผนผลิต | รอบผลิต |\n|---|---|---:|---:|---:|---|\n{top}")

    # 3) เสี่ยงของขาด
    if re.search(r"เสี่ยง|ของขาด|ขาดสต๊อก|ขาดสต็อก|stockout", t, re.I):
        r = tools["stockout_watch"](",".join(groups) or "AX,AY,BX")
        rows = "\n".join(f"| {i['sku']} | {i.get('ABC_XYZ')} | {_f(i.get('recent3'))} | {_f(i.get('fc_next'))} | {i.get('risk_flags') or ''} |"
                         for i in r["items"][:10])
        return (f"**เฝ้าระวังของขาด ({', '.join(groups) or 'AX, AY, BX'})** — เสี่ยง **{r['at_risk']}** จาก {r['checked']} SKU "
                f"(เทียบ forecast {r['next_month']})\n\n"
                f"| รหัส | กลุ่ม | ขายเฉลี่ย 3 ด. | FC เดือนหน้า | สาเหตุ |\n|---|---|---:|---:|---|\n{rows}")
    return None
