# Glory FCC API Usage Decisions

## Cash Inventory Endpoints

| Endpoint | Cash Type | Returns | Used By |
|---|---|---|---|
| `/fcc/api/v1/cash/availability` | Type 4 — Dispensable | Only denominations the machine can dispense right now | `check_float` → JS stacker cylinders display |
| `/fcc/api/v1/cash/inventory` | Type 3 — Stock (all) | ALL cash in machine including feeder/buffer | `pos_commands._glory_get_inventory()` → collection/greedy algorithm |
| `/fcc/api/v1/cash/cassette` | CashUnits (Option type=3) | Physical stacker slots only (by unitno whitelist) | Cassette strip bar |

## Rules — DO NOT change these without discussion

1. **Stacker cylinders (processedInventory in JS)** → MUST use `state.availability`
   which comes from `bridgeApiAvailability` → `/cash/availability` (type=4)
   REASON: Type 4 matches FCC Listener Cash Out form exactly.

2. **Collection greedy algorithm** (`pos_commands._glory_get_inventory`) → MUST use `/cash/inventory` (type=3)
   REASON: Type 4 excludes ฿1,000 notes (availability=False due to FCC setting),
   causing them to be skipped during collection.

3. **Cassette strip bar** → MUST use `/cash/cassette` (CashUnits, unitno whitelist)
   REASON: Counts physical pieces in stacker slots only.

4. **EUR→THB mapping** → slot-based filter only, NO remapping
   REASON: FCC fv values identify cassette slot positions — same number in EUR or THB.
   fv=5000 = ฿50 slot always. Just filter against THB_NOTE_SLOTS/THB_COIN_SLOTS.

## Current correct flow

```
check_float (Odoo)
  ├── /cash/inventory  → bridgeApiInventory   (kept for reference, not used for display)
  └── /cash/availability → bridgeApiAvailability → processedInventory → stacker cylinders ✓

get_cassette_inventory (Odoo)
  └── /cash/cassette → _build_thb_inventory (slot filter) → cassette strip bar ✓

pos_commands._glory_get_inventory (Flask/Odoo backend)
  └── /cash/inventory (type=3) → greedy algorithm → collection ✓
```