# Demand Planning Dashboard (Streamlit)

Dashboard วางแผนความต้องการ — โทนสีเข้มแบบเดียวกับ OEE dashboard
อ่านข้อมูลตรงจาก Google Sheet *Demand Planning ABC* · หน่วยวัดเป็น **จำนวน** · ยอดขายนับเฉพาะบิล **NV / IV**

## ติดตั้งและรัน

```bash
pip install -r requirements.txt
streamlit run app.py
```

## หน้า (เมนูซ้าย)

| กลุ่ม | หน้า | เนื้อหา |
|---|---|---|
| วางแผนความต้องการ | 🎯 **Forecast vs Actual** (หน้าแรก) | Accuracy / Bias / SKU แม่น ≥80% · แนวโน้มรายเดือน · แยกหมวด/ABC/Tier · SKU ที่คลาดมากสุด · SKU ที่ยังไม่มี forecast |
| | 🔤 **ABC-XYZ Grade** | ตาราง ABC×XYZ · Pareto · Priority tier · รายการ SKU |
| | 🛡️ **Safety Stock & ROP** | SS / ROP / Target / Lead time · SS คิดเป็นกี่เดือน · forecast เดือนหน้าที่ควรตรวจ |
| | 🔍 **ดูราย SKU** | กราฟยอดขาย 24 เดือน + forecast + ค่าเฉลี่ย |
| สินค้าคงคลัง | 📦 **Non-moving Inventory** | *รอข้อมูลสต๊อก* |
| ระบบ | 🧹 **คุณภาพข้อมูล** | รหัสซ้ำใน Forecast, กลุ่ม A ไม่มี forecast, Inactive แต่ยังขาย ฯลฯ |

ตัวกรองด้านซ้าย (หมวด, ABC, XYZ, Tier, Production, ไม่รวม Inactive) ใช้ได้ทุกหน้า

## หลักการคำนวณ Forecast vs Actual

- **เทียบเฉพาะ SKU ที่อยู่ในชีต Forecast** — SKU ที่ไม่มี forecast ไม่ถูกนับ (แสดงแยกในแท็บ *ยังไม่มี Forecast*)
- **Actual** = จำนวนจ่ายจากบิล NV / IV
- **Forecast Accuracy** = 1 − WAPE, **WAPE** = Σ|F − A| ÷ ΣA, **Bias** = (ΣF − ΣA) ÷ ΣA
- ผลรวมหน่วยรวมหลายหน่วยนับ (ม้วน/ชิ้น) — ดูแยกตาม *หมวด* เพื่อเทียบหน่วยเดียวกัน
- เพิ่มเดือนใหม่ในชีต Forecast เป็นคอลัมน์ `Forecast_YYYYMM` ได้เลย ระบบอ่านเอง
- **ล็อกตัวเลข forecast ก่อนเริ่มเดือน** ถ้าแก้ระหว่างเดือน accuracy จะดีเกินจริง

## แหล่งข้อมูล (⚙️ ที่แถบซ้าย)

| ตัวเลือก | ใช้เมื่อ |
|---|---|
| **Google Sheet** (ค่าตั้งต้น) | ชีตแชร์แบบ *ทุกคนที่มีลิงก์ดูได้* — ดึงใหม่อัตโนมัติทุก 10 นาที หรือกด *ดึงข้อมูลใหม่ตอนนี้* |
| **อัปโหลด Excel** | ชีตเป็นส่วนตัว — File > Download > .xlsx แล้วอัปโหลด |
| **โฟลเดอร์ CSV** | ทำงานออฟไลน์ — ไฟล์ชื่อ `<ชื่อชีต>.csv` |

เปลี่ยนลิงก์ตั้งต้นได้ที่ `.streamlit/secrets.toml` (ดู `secrets.toml.example`)

## โลโก้

วางไฟล์ `assets/logo.png` (หรือ .jpg / .svg) แล้วจะแสดงในกล่อง header ทุกหน้า

## โครงสร้างไฟล์

```
app.py            จุดเริ่ม: โหลดข้อมูล เมนูซ้าย ตัวกรอง
dp_core.py        ส่วนคำนวณทั้งหมด (pandas ล้วน)
ui.py             ธีม การ์ด KPI header และรูปแบบกราฟ
views/            แต่ละหน้า (forecast, abc, safety, sku, nonmoving, quality)
.streamlit/       ธีมสีเข้ม และตัวอย่าง secrets
```

## Deploy บน Streamlit Community Cloud

push โฟลเดอร์นี้ขึ้น GitHub → share.streamlit.io → New app → เลือก `app.py` → ใส่ `sheet_url` ใน Secrets
