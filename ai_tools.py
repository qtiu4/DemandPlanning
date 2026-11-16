"""
ai_tools.py — เครื่องมือที่ผู้ช่วย AI (Gemini) เรียกใช้ได้

หลักการ: AI ไม่คำนวณตัวเลขเอง ทุกตัวเลขมาจากฟังก์ชันใน dp_core
ข้อมูลที่ส่งกลับให้ AI เป็นผลสรุปของ SKU ที่ถามเท่านั้น (ไม่มีรายบิล / ลูกค้า / ราคาทุน)
"""
from __future__ import annotations

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
            y = y + 2500 if y < 100 else y
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


def make_tools(model: dp.Model, sink: list):
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

    def pr_suggestion(sku: str, on_hand: float, on_order: float = 0.0, lot_size: float = 1.0,
                      review_months: float = 1.0) -> dict:
        """คำนวณว่าควรเปิด PR (ผลิต/สั่งซื้อ) หรือไม่ และจำนวนเท่าไร สำหรับ SKU หนึ่งตัว
        ต้องมีสต๊อกคงเหลือปัจจุบัน (on_hand) — ถ้าผู้ใช้ไม่บอก ให้ถามก่อน
        on_order = ของที่สั่ง/ผลิตค้างรับอยู่, lot_size = ปัดขึ้นทีละกี่หน่วย, review_months = รอบวางแผน (เดือน)"""
        rows = pd.DataFrame([{"sku": sku.strip(), "on_hand": on_hand, "on_order": on_order, "lot_size": lot_size}])
        res = dp.pr_calc(model, rows, review_months)
        if res.empty or "pr_qty" not in res:
            return {"error": f"ไม่พบรหัส {sku}"}
        sink.append((f"คำนวณ PR — {sku}", res))
        r = res.iloc[0]
        return {k: (_num(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()
                if k in ("sku", "name", "ABC_XYZ", "on_hand", "on_order", "demand_month", "demand_basis",
                         "lead_time_days", "safety_stock", "rop", "target", "cover_months", "status", "pr_qty")}

    def production_plan(month: str = "", skus: str = "", abc_xyz: str = "", tier: str = "",
                        category: str = "", weekly: bool = True, top_n: int = 25) -> dict:
        """แผนผลิตของเดือนที่ระบุ (หน่วย: จำนวน) พร้อมแบ่งรายสัปดาห์ตามสัดส่วนยอดขายในอดีต
        month: เช่น '2026-12' หรือ 'ธ.ค.' (เว้นว่าง = เดือนถัดไป)
        skus: รหัสคั่นด้วยจุลภาค (เว้นว่าง = ทุก SKU ที่มี forecast เดือนนั้น)
        abc_xyz: กรองกลุ่ม เช่น 'AX,AY' · tier: เช่น 'A1-Core' · category: หมวด เช่น '1,3'
        แผนผลิต = Forecast ของเดือน (ถ้าไม่มีใช้ค่าเฉลี่ย) ยังไม่หักสต๊อกคงเหลือ"""
        mo = parse_month(month, model)
        sku_list = _split(skus) or None
        df = dp.production_plan(model, mo, sku_list, weekly=weekly)
        if df.empty:
            return {"month": dp.month_label(mo), "error": "ไม่มี SKU ที่ตรงเงื่อนไข หรือยังไม่มี forecast เดือนนี้"}
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
            "week_split_method": "สัดส่วนยอดขาย 12 เดือนล่าสุดตามสัปดาห์ของเดือน (SKU → หมวด → ภาพรวม)",
            "rows_shown": min(top_n, len(df)),
            "items": _records(df, ["sku", "name", "ABC_XYZ", "demand_basis", "plan_qty", *wcols], top_n),
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
4. การคำนวณ PR ต้องรู้สต๊อกคงเหลือ ถ้าผู้ใช้ไม่บอก ให้ถามก่อน (ยังไม่มีข้อมูลสต๊อกในระบบ)
5. แผนผลิตรายสัปดาห์แบ่งตามสัดส่วนยอดขายในอดีตของแต่ละสัปดาห์ในเดือน (W1 = วันที่ 1–7 ... W5 = 29–สิ้นเดือน) บอกผู้ใช้ด้วย
6. บอกเสมอว่าความต้องการมาจาก Forecast หรือค่าเฉลี่ยในอดีต
7. สรุปตัวเลขสำคัญในคำตอบ ตารางเต็มระบบจะแสดงใต้คำตอบเอง ไม่ต้องพิมพ์ตารางยาวซ้ำ (แสดงไม่เกิน 10 แถว)
8. ตอบเฉพาะเรื่องการวางแผนผลิต/สต๊อก/ยอดขายของบริษัท

บริบท: ข้อมูลยอดขาย (บิล NV/IV) ถึง {model.last_date:%d/%m/%Y} · เดือนที่วางแผนถัดไป = {dp.month_label(nxt)} ·
มี forecast เดือน {', '.join(dp.month_label(x) for x in model.fc_months)}"""
