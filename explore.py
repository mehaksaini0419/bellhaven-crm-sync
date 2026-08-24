"""Run this FIRST. It only reads, and it tells you the shape of everything.

    python explore.py
"""
import json
from collections import Counter
import config
from crm_client import CRMClient

crm = CRMClient()

print("=" * 62)
print("1. WHO AM I")
print("=" * 62)
print(json.dumps(crm._get("/me"), indent=2)[:400])

print()
print("=" * 62)
print("2. RAW SHAPE OF /accounts")
print("=" * 62)
raw = crm._get("/accounts", page=1, page_size=3)
print("top-level type:", type(raw).__name__)
if isinstance(raw, dict):
    print("top-level keys:", list(raw.keys()))
print(json.dumps(raw, indent=2)[:1400])

print()
print("=" * 62)
print("3. ALL ACCOUNTS")
print("=" * 62)
accounts = crm.list_accounts()
print(f"pulled {len(accounts)} accounts")
if accounts:
    print("fields:", sorted(accounts[0].keys()))

parents = [a for a in accounts if not a.get("parent_id")]
print(f"\ntop-level accounts (no parent): {len(parents)}")
for p in parents:
    kids = [a for a in accounts if a.get("parent_id") == p["account_id"]]
    print(f"  {p['account_id']}  {p.get('name','')[:45]:47} children={len(kids)}")

print()
print("=" * 62)
print("4. FIELD COVERAGE")
print("=" * 62)
for f in ["parent_id", "status", "care_type", "billing_street", "billing_zip",
          "lifetime_revenue", "outstanding_ar", "chow_current_account",
          "duplicate_of_account", "note"]:
    filled = sum(1 for a in accounts if a.get(f) not in (None, "", 0))
    print(f"  {f:24} populated on {filled:3}/{len(accounts)}")

print()
print("  status values:", dict(Counter(a.get("status") for a in accounts)))

print()
print("=" * 62)
print("5. ACCOUNTS WITH BOTH REVENUE AND OUTSTANDING AR  (the CHOW cases)")
print("=" * 62)
for a in accounts:
    rev = float(a.get("lifetime_revenue") or 0)
    ar = float(a.get("outstanding_ar") or 0)
    if rev > 0 and ar > 0:
        print(f"  {a['account_id']}  {a.get('name','')[:40]:42} rev=${rev:>10,.0f}  ar=${ar:>9,.0f}")

print()
print("=" * 62)
print("6. NAME COLLISIONS (possible duplicates)")
print("=" * 62)
c = Counter((a.get("name") or "").strip().lower() for a in accounts)
for name, n in c.most_common():
    if n > 1:
        print(f"  x{n}  {name}")

json.dump(accounts, open("data_accounts_snapshot.json", "w"), indent=2, default=str)
print("\nsnapshot written to data_accounts_snapshot.json")
