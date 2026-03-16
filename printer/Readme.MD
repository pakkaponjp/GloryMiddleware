# Print Service — Xprinter XP-T80Q

Flask service สำหรับพิมพ์ใบเสร็จผ่าน USB thermal printer บน Windows

## Setup

```bash
pip install -r requirements.txt
```

## หา Vendor/Product ID ของ Xprinter

1. เปิด Device Manager
2. Universal Serial Bus controllers → ดู Properties → Details → Hardware Ids
3. แก้ไขค่าใน `printer.py`:
```python
XPRINTER_VENDOR_ID  = 0x0483   # แก้ตามเครื่องจริง
XPRINTER_PRODUCT_ID = 0x5720   # แก้ตามเครื่องจริง
```

หรือใช้ Python ตรวจสอบ:
```python
import usb.core
for dev in usb.core.find(find_all=True):
    print(f"VID={hex(dev.idVendor)} PID={hex(dev.idProduct)}")
```

## Run

```bash
python app.py
```

Service รันที่ port **5001**

## Test (ไม่ต้องมีเครื่องพิมพ์)

```bash
python test_print.py
```

## Endpoints

| Method | Path | คำอธิบาย |
|--------|------|----------|
| GET | /health | Health check |
| POST | /print/deposit | ใบเสร็จ Cash Deposit |
| POST | /print/withdrawal | ใบเสร็จ Cash Withdrawal |
| POST | /print/close_shift | ใบสรุปปิดกะ |
| POST | /print/eod | ใบสรุป End of Day |
| POST | /print/collect_cash | ใบเสร็จ Collect Cash |

## ตัวอย่าง curl (Deposit)

```bash
curl -X POST http://localhost:5001/print/deposit \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "ปั๊ม พี พาวเวอร์",
    "branch_name": "สาขาหลัก",
    "address": "123 ถ.สุขุมวิท กรุงเทพฯ",
    "phone": "02-xxx-xxxx",
    "reference": "TXN-1773617438540",
    "deposit_type": "oil",
    "staff_name": "Attendant01",
    "datetime_str": "16/03/2026 14:30:25",
    "breakdown": {
      "notes": [
        {"qty": 2, "value": 2000},
        {"qty": 1, "value": 5000}
      ],
      "coins": []
    },
    "total_satang": 9000
  }'
```