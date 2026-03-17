# Glory Middleware — Deployment Guide

## Architecture

```
Windows Machine (UAT / Test)
┌──────────────────────────────────────┐
│  Docker                              │
│  ┌─────────────┐  ┌───────────────┐ │
│  │  Odoo 17    │  │ PostgreSQL 16 │ │
│  │  port 8069  │  │               │ │
│  └─────────────┘  └───────────────┘ │
│                                      │
│  Windows Native Services (NSSM)      │
│  ┌──────────┐ ┌─────────┐ ┌──────┐ │
│  │ GloryAPI │ │ Printer │ │ Fing │ │
│  │ :5000    │ │ :5006   │ │ :500X│ │
│  └──────────┘ └─────────┘ └──────┘ │
└──────────────────────────────────────┘
```

---

## First Time Setup

### 1. Install Docker Desktop (Windows)
https://docs.docker.com/desktop/install/windows-install/

### 2. Clone repo
```bash
git clone <repo_url> C:\GloryMiddleware
cd C:\GloryMiddleware
```

### 3. Setup environment
```bash
# สร้าง .env จาก template
cp .env.example .env

# แก้ค่าใน .env
# POSTGRES_PASSWORD=ใส่ password จริง
```

### 4. Setup odoo.conf
```bash
# สร้าง config folder (ถ้าไม่มี)
mkdir config

# copy template แล้วแก้ค่า
cp config/odoo.conf.example config/odoo.conf

# แก้ค่าใน config/odoo.conf:
# db_password   = ตรงกับ .env
# printer_api_host = IP เครื่อง Windows printer
# fcc_currency  = THB (เครื่องจริง) หรือ EUR (emulator)
```

### 5. Start Docker
```bash
docker compose up -d
```

### 6. Install Odoo modules (ครั้งแรกเท่านั้น)
```bash
docker exec glory_odoo odoo -c /etc/odoo/odoo.conf \
    -d odoo \
    -i gas_station_cash,gas_station_erp_mini,glory_cash_inventory_dashboard,glory_machine_control \
    --stop-after-init

docker compose start odoo
```

### 7. Setup Windows Services
```
1. วาง nssm.exe ใน C:\GloryMiddleware\tools\
2. รัน setup_services.bat ในฐานะ Administrator
3. ตรวจสอบที่ services.msc
```

---

## Update / Deploy

```bash
# Pull latest code
git pull origin main

# Restart Odoo
docker compose restart odoo

# ถ้ามี model/view เปลี่ยน — upgrade module
docker exec glory_odoo odoo -c /etc/odoo/odoo.conf \
    -d odoo \
    -u gas_station_cash,glory_machine_control \
    --stop-after-init
docker compose start odoo

# Update Flask services
nssm restart GloryAPI
nssm restart PrinterService
```

---

## Useful Commands

```bash
# ดู logs
docker compose logs -f odoo
docker compose logs -f db

# Backup database
docker exec glory_postgres pg_dump -U odoo odoo > backup_$(date +%Y%m%d).sql

# Stop all
docker compose down

# Reset database (ระวัง! ลบข้อมูลทั้งหมด)
docker compose down -v
```