"""
dp_core.py — ส่วนคำนวณทั้งหมดของ Demand Planning Dashboard (ไม่พึ่ง Streamlit)

โหลดข้อมูลจาก Google Sheet / ไฟล์ Excel / โฟลเดอร์ CSV แล้วสร้าง:
  - sales      : รายการขายจริง (NV/IV) ระดับบิล
  - monthly    : ยอดขายรายเดือนต่อ SKU (qty, value)
  - master     : ข้อมูล SKU จาก Cal ABC_XYZ + Info + LeadTime
  - fc         : Forecast แบบ long (sku, month, forecast_qty)
  - accuracy   : Forecast เทียบ Actual ระดับ SKU-เดือน
"""
from __future__ import annotations

import io
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- ค่าตั้งต้น
DEMAND_DOCS = ("NV", "IV")          # เอกสารที่นับเป็นยอดขายจริง
SHEET_SALES = "Sale Transaction"
SHEET_FC = "Forecast"
SHEET_CAL = "Cal ABC_XYZ"
SHEET_INFO = "Info"
SHEET_LT = "LeadTime"
SHEET_CONFIG = "Config"

TH_MONTH = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


# ---------------------------------------------------------------- helpers
def month_label(mk: int) -> str:
    """202609 -> 'ก.ย. 26'"""
    mk = int(mk)
    return f"{TH_MONTH[mk % 100 - 1]} {str(mk // 100)[2:]}"


def month_add(mk: int, n: int) -> int:
    y, m = divmod(int(mk) // 100 * 12 + int(mk) % 100 - 1 + n, 12)
    return y * 100 + m + 1


def month_range(start: int, end: int) -> list[int]:
    out, m = [], int(start)
    while m <= int(end):
        out.append(m)
        m = month_add(m, 1)
    return out


def to_num(s: pd.Series) -> pd.Series:
    """'95,420.15' / '' / 1.0 -> float"""
    if s.dtype.kind in "if":
        return s.astype(float)
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip()
         .replace({"": np.nan, "nan": np.nan, "None": np.nan, "-": np.nan}),
        errors="coerce",
    )


def _clean_str(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().replace({"nan": "", "None": ""})


def sheet_id_from_url(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else url.strip()


# ---------------------------------------------------------------- loaders
def load_gsheet(url_or_id: str, timeout: int = 120) -> dict[str, pd.DataFrame]:
    """ดาวน์โหลดทั้งไฟล์เป็น .xlsx (ต้องแชร์แบบ 'ทุกคนที่มีลิงก์ดูได้')"""
    sid = sheet_id_from_url(url_or_id)
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    if data[:2] != b"PK":
        raise RuntimeError("ดาวน์โหลดไม่ได้ — ตรวจสอบว่าแชร์ชีตแบบ 'ทุกคนที่มีลิงก์สามารถดูได้'")
    return load_xlsx(data)


def load_xlsx(data: bytes) -> dict[str, pd.DataFrame]:
    xl = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object)
    return {k.strip(): v for k, v in xl.items()}


def load_csv_dir(path: str | Path) -> dict[str, pd.DataFrame]:
    """โฟลเดอร์ที่มีไฟล์ <ชื่อชีต>.csv (ใช้ทดสอบ / ทำงานออฟไลน์)"""
    out = {}
    for p in Path(path).glob("*.csv"):
        try:
            out[p.stem.strip()] = pd.read_csv(p, dtype=str, keep_default_na=False)
        except pd.errors.ParserError:      # ชีตที่ไม่ใช่ตาราง (เช่น CRITERIA) ข้ามไป
            continue
    return out


# ---------------------------------------------------------------- model
@dataclass
class Model:
    sales: pd.DataFrame
    monthly: pd.DataFrame
    master: pd.DataFrame
    fc: pd.DataFrame
    config: dict
    last_date: pd.Timestamp
    issues: dict = field(default_factory=dict)

    # เดือนล่าสุดที่มีข้อมูล และข้อมูลครบเดือนหรือไม่
    @property
    def last_month(self) -> int:
        return int(self.last_date.year * 100 + self.last_date.month)

    @property
    def last_month_complete(self) -> bool:
        return self.last_date.day == self.last_date.days_in_month

    @property
    def fc_months(self) -> list[int]:
        return sorted(self.fc["month"].unique().tolist())


def _parse_dates(s: pd.Series) -> pd.Series:
    """รองรับทั้ง datetime จาก Excel และข้อความ d/m/yyyy (ปี พ.ศ. ด้วย)"""
    # แยกเป็น ปี/เดือน/วัน ก่อน แล้วแก้ปี พ.ศ. (ปี > 2400 ลบ 543) ค่อยประกอบเป็นวันที่
    y = pd.Series(np.nan, index=s.index)
    mo, d = y.copy(), y.copy()
    is_dt = s.map(lambda v: hasattr(v, "year") and hasattr(v, "month"))
    if is_dt.any():
        y[is_dt] = s[is_dt].map(lambda v: v.year)
        mo[is_dt] = s[is_dt].map(lambda v: v.month)
        d[is_dt] = s[is_dt].map(lambda v: v.day)
    txt = s[~is_dt].astype(str).str.strip()
    parts = txt.str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
    ok = parts.notna().all(axis=1)
    idx = ok[ok].index
    d[idx], mo[idx], y[idx] = (parts.loc[idx, i].astype(float) for i in range(3))
    y = y.where(y < 2400, y - 543)
    good = y.notna() & mo.notna() & d.notna()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[good] = pd.to_datetime(dict(year=y[good].astype(int), month=mo[good].astype(int),
                                    day=d[good].astype(int)), errors="coerce")
    return out


def build_model(raw: dict[str, pd.DataFrame]) -> Model:
    issues: dict[str, pd.DataFrame] = {}

    # ---- Sales
    st = raw[SHEET_SALES].copy()
    st.columns = [str(c).strip() for c in st.columns]
    st["sku"] = _clean_str(st["รหัสสินค้า"])
    st["doc"] = _clean_str(st["ประเภทเอกสาร"]).str.upper()
    st["date"] = _parse_dates(st["วันที่"])
    st["qty"] = to_num(st["จำนวนจ่าย"]).fillna(0)
    st["value"] = to_num(st["มูลค่าจ่าย"]).fillna(0)
    st = st[st["doc"].isin(DEMAND_DOCS) & st["date"].notna() & (st["sku"] != "")]
    st["month"] = st["date"].dt.year * 100 + st["date"].dt.month
    sales = st[["sku", "ชื่อสินค้า", "date", "month", "doc", "qty", "value"]].rename(
        columns={"ชื่อสินค้า": "name"})
    last_date = sales["date"].max()

    monthly = (sales.groupby(["sku", "month"], as_index=False)[["qty", "value"]].sum())

    # ราคาเฉลี่ยต่อหน่วย 12 เดือนล่าสุด (ใช้แปลง forecast เป็นมูลค่า)
    lm = int(last_date.year * 100 + last_date.month)
    recent = monthly[monthly["month"] > month_add(lm, -12)]
    price = recent.groupby("sku")[["qty", "value"]].sum()
    price_all = monthly.groupby("sku")[["qty", "value"]].sum()
    unit_price = (price["value"] / price["qty"].replace(0, np.nan)).combine_first(
        price_all["value"] / price_all["qty"].replace(0, np.nan))

    # ---- Master (Cal ABC_XYZ + Info + LeadTime)
    cal = raw.get(SHEET_CAL, pd.DataFrame()).copy()
    cal.columns = [str(c).strip() for c in cal.columns]
    if len(cal):
        cal = cal.rename(columns={"รหัส SKU": "sku", "ชื่อสินค้า": "name", "หมวด": "category"})
        cal["sku"] = _clean_str(cal["sku"])
        cal = cal[cal["sku"] != ""].drop_duplicates("sku")
        num_cols = ["total_value", "pct_of_value", "cum_pct_value", "total_qty", "mean_monthly_qty",
                    "std_monthly_qty", "cv", "active_months", "last_sale_month", "value_rank",
                    "safety_stock", "reorder_point", "target_stock", "lead_time_days",
                    "first_sale_month", "n_months_eff", "category"]
        for c in num_cols:
            if c in cal:
                cal[c] = to_num(cal[c])
        for c in ["ABC", "XYZ", "ABC_XYZ", "priority_tier"]:
            if c in cal:
                cal[c] = _clean_str(cal[c])
    master = cal

    info = raw.get(SHEET_INFO)
    if info is not None and len(info):
        info = info.rename(columns={"รหัส SKU": "sku"}).copy()
        info["sku"] = _clean_str(info["sku"])
        keep = [c for c in ["sku", "Status", "Production"] if c in info]
        info = info[keep].drop_duplicates("sku")
        for c in keep[1:]:
            info[c] = _clean_str(info[c])
        master = master.merge(info, on="sku", how="outer") if len(master) else info

    if "name" not in master:
        master["name"] = ""
    names = sales.drop_duplicates("sku", keep="last").set_index("sku")["name"]
    master["name"] = master["name"].where(master["name"].astype(str).str.len() > 0,
                                          master["sku"].map(names))
    master["unit_price"] = master["sku"].map(unit_price)

    # ---- วันที่ขายครั้งแรก / ล่าสุด (NV/IV) และยอด 12 เดือน
    master["first_sale_date"] = master["sku"].map(sales.groupby("sku")["date"].min())
    master["last_sale_date"] = master["sku"].map(sales.groupby("sku")["date"].max())
    master["days_since_sale"] = (last_date - master["last_sale_date"]).dt.days
    s12 = monthly[monthly["month"] > month_add(lm, -12)].groupby("sku")[["qty", "value"]].sum()
    master["qty_12m"] = master["sku"].map(s12["qty"]).fillna(0)
    master["value_12m"] = master["sku"].map(s12["value"]).fillna(0)
    for c, d in [("ABC", "-"), ("XYZ", "-"), ("ABC_XYZ", "-"), ("priority_tier", "นอกกลุ่ม A"),
                 ("Status", "-"), ("Production", "-")]:
        if c not in master:
            master[c] = d
        master[c] = master[c].replace({"": d}).fillna(d)
    if "category" not in master:
        master["category"] = np.nan

    # ---- Forecast (wide -> long)
    fcw = raw.get(SHEET_FC, pd.DataFrame()).copy()
    fcw.columns = [str(c).strip() for c in fcw.columns]
    fcw = fcw.rename(columns={"รหัส SKU": "sku", "ชื่อสินค้า": "fc_name"})
    fcw["sku"] = _clean_str(fcw["sku"])
    fcw = fcw[fcw["sku"] != ""]
    dup = fcw[fcw["sku"].duplicated(keep=False)]
    if len(dup):
        issues["forecast_duplicate"] = dup[["sku", "fc_name"]]
    fcw = fcw.drop_duplicates("sku", keep="first")
    mcols = {c: int(m.group(1)) for c in fcw.columns if (m := re.match(r"Forecast_(\d{6})$", c))}
    fc = fcw.melt(id_vars=["sku"], value_vars=list(mcols), var_name="col", value_name="forecast_qty")
    fc["month"] = fc["col"].map(mcols)
    fc["forecast_qty"] = to_num(fc["forecast_qty"])
    fc = fc.dropna(subset=["forecast_qty"])[["sku", "month", "forecast_qty"]]

    # ---- ตรวจคุณภาพข้อมูล
    sold = set(sales["sku"])
    known = set(master["sku"]) | sold
    fc_skus = fcw[["sku", "fc_name"]]
    issues["forecast_not_in_master"] = fc_skus[~fc_skus["sku"].isin(known)]
    issues["forecast_never_sold"] = fc_skus[fc_skus["sku"].isin(known) & ~fc_skus["sku"].isin(sold)]

    # ---- Config
    cfg = {}
    c = raw.get(SHEET_CONFIG)
    if c is not None and len(c):
        row = c.iloc[0]
        for k in c.columns:
            v = to_num(pd.Series([row[k]])).iloc[0]
            cfg[str(k).strip()] = v if pd.notna(v) else row[k]

    return Model(sales=sales, monthly=monthly, master=master, fc=fc, config=cfg,
                 last_date=last_date, issues=issues)


# ---------------------------------------------------------------- accuracy
def accuracy_frame(model: Model, months: list[int] | None = None,
                   skus: list[str] | None = None) -> pd.DataFrame:
    """Forecast vs Actual ระดับ SKU-เดือน (เฉพาะเดือนที่มี forecast และมียอดขายจริงแล้ว)"""
    fc = model.fc
    if months is None:
        months = [m for m in model.fc_months if m <= model.last_month]
    fc = fc[fc["month"].isin(months)]
    act = model.monthly[model.monthly["month"].isin(months)]
    df = fc.merge(act[["sku", "month", "qty"]], on=["sku", "month"], how="left")
    df["actual_qty"] = df.pop("qty").fillna(0.0)
    if skus is not None:
        df = df[df["sku"].isin(skus)]
    price = model.master.set_index("sku")["unit_price"]
    df["unit_price"] = df["sku"].map(price).fillna(0)
    df["error"] = df["forecast_qty"] - df["actual_qty"]          # + = พยากรณ์เกิน
    df["abs_error"] = df["error"].abs()
    df["forecast_value"] = df["forecast_qty"] * df["unit_price"]
    df["actual_value"] = df["actual_qty"] * df["unit_price"]
    df["abs_error_value"] = df["abs_error"] * df["unit_price"]
    df["error_value"] = df["error"] * df["unit_price"]
    # Accuracy รายแถว: 1 - |F-A|/A (ตัดที่ 0..1), A=0 & F=0 -> 1, A=0 & F>0 -> 0
    with np.errstate(divide="ignore", invalid="ignore"):
        acc = 1 - df["abs_error"] / df["actual_qty"]
    acc = acc.where(df["actual_qty"] > 0, np.where(df["forecast_qty"] == 0, 1.0, 0.0))
    df["accuracy"] = acc.clip(0, 1)
    df["direction"] = np.select([df["error"] > 0, df["error"] < 0], ["เกิน", "ขาด"], "ตรง")
    m = model.master.set_index("sku")
    for c in ["name", "ABC", "XYZ", "ABC_XYZ", "priority_tier", "category", "Status", "Production"]:
        if c in m:
            df[c] = df["sku"].map(m[c])
    return df


def summarize(df: pd.DataFrame, by: str | list[str] | None = None, basis: str = "qty") -> pd.DataFrame:
    """WAPE / Accuracy / Bias — basis = 'qty' (หน่วย) หรือ 'value' (บาท)"""
    a, f, ae = (("actual_qty", "forecast_qty", "abs_error") if basis == "qty"
                else ("actual_value", "forecast_value", "abs_error_value"))

    def agg(g: pd.DataFrame) -> pd.Series:
        A, F, AE = g[a].sum(), g[f].sum(), g[ae].sum()
        wape = AE / A if A > 0 else np.nan
        return pd.Series({
            "n_sku": g["sku"].nunique(),
            "actual": A, "forecast": F,
            "abs_error": AE,
            "wape": wape,
            "accuracy": max(0.0, 1 - wape) if pd.notna(wape) else np.nan,
            "bias": (F - A) / A if A > 0 else np.nan,
            "sku_hit_rate": (g["accuracy"] >= 0.8).mean() if len(g) else np.nan,
        })

    if by is None:
        return agg(df).to_frame().T
    return df.groupby(by, dropna=False).apply(agg, include_groups=False).reset_index()


def sku_tracking(df: pd.DataFrame) -> pd.DataFrame:
    """สรุปราย SKU หลายเดือน + Tracking Signal (ผลรวม error / MAD)"""
    g = df.groupby("sku")
    out = pd.DataFrame({
        "months": g["month"].nunique(),
        "forecast": g["forecast_qty"].sum(),
        "actual": g["actual_qty"].sum(),
        "sum_error": g["error"].sum(),
        "mad": g["abs_error"].mean(),
        "abs_error_value": g["abs_error_value"].sum(),
    })
    out["wape"] = (g["abs_error"].sum() / out["actual"].replace(0, np.nan))
    out["accuracy"] = (1 - out["wape"]).clip(lower=0)
    out["bias"] = out["sum_error"] / out["actual"].replace(0, np.nan)
    out["tracking_signal"] = out["sum_error"] / out["mad"].replace(0, np.nan)
    return out.reset_index()


# ---------------------------------------------------------------- planning
def planning_table(model: Model, n_ahead: int = 3) -> pd.DataFrame:
    """ตารางวางแผน: SS / ROP / Target + forecast เดือนถัดไป + ธงที่ควรตรวจ"""
    m = model.master.copy()
    future = [mk for mk in model.fc_months if mk > model.last_month][:n_ahead]
    if future:
        fw = (model.fc[model.fc["month"].isin(future)]
              .pivot_table(index="sku", columns="month", values="forecast_qty", aggfunc="sum"))
        fw.columns = [f"F {month_label(c)}" for c in fw.columns]
        m = m.merge(fw, left_on="sku", right_index=True, how="left")
        first = f"F {month_label(future[0])}"
        mean = m.get("mean_monthly_qty", pd.Series(np.nan, index=m.index))
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = m[first] / mean
        m["fc_vs_mean"] = ratio
        flags = []
        for r, f, tier, rop in zip(ratio, m[first], m["priority_tier"],
                                   m.get("reorder_point", pd.Series(np.nan, index=m.index))):
            fl = []
            if tier == "A4-Fading" and (f or 0) > 0:
                fl.append("Fading แต่ยังมี forecast")
            if pd.notna(r) and np.isfinite(r) and r > 1.5:
                fl.append("forecast สูงกว่าค่าเฉลี่ย >50%")
            if pd.notna(r) and np.isfinite(r) and r < 0.5 and (f or 0) > 0:
                fl.append("forecast ต่ำกว่าค่าเฉลี่ย >50%")
            if pd.isna(f) and str(tier).startswith("A") and tier != "A4-Fading":
                fl.append("กลุ่ม A ไม่มี forecast")
            flags.append(", ".join(fl))
        m["review_flag"] = flags
    return m


# ---------------------------------------------------------------- trends
def monthly_totals(model: Model, skus: list[str] | None = None) -> pd.DataFrame:
    mo = model.monthly if skus is None else model.monthly[model.monthly["sku"].isin(skus)]
    act = mo.groupby("month")[["qty", "value"]].sum()
    fc = model.fc if skus is None else model.fc[model.fc["sku"].isin(skus)]
    price = model.master.set_index("sku")["unit_price"]
    fc = fc.assign(fv=fc["forecast_qty"] * fc["sku"].map(price).fillna(0))
    f = fc.groupby("month")[["forecast_qty", "fv"]].sum().rename(columns={"fv": "forecast_value"})
    out = act.join(f, how="outer").reset_index()
    past = out["month"] <= model.last_month
    out.loc[past, ["qty", "value"]] = out.loc[past, ["qty", "value"]].fillna(0)
    out["label"] = out["month"].map(month_label)
    return out.sort_values("month")
