"""Ad-hoc lookup against the CRM snapshot, for checking a proposal by hand.

    python lookup.py Hudson          # anything whose city/name/street contains "hudson"
    python lookup.py "Amberly"
    python lookup.py 44236
"""
import json
import sys

accounts = json.load(open("data_accounts_snapshot.json"))
needle = " ".join(sys.argv[1:]).lower()

if not needle:
    print("usage: python lookup.py <search term>")
    raise SystemExit

hits = []
for a in accounts:
    hay = " ".join(str(a.get(f, "")) for f in
                   ["name", "billing_street", "billing_city", "billing_state",
                    "billing_zip", "parent_name"]).lower()
    if needle in hay:
        hits.append(a)

print(f'{len(hits)} account(s) matching "{needle}"\n')
for a in hits:
    print(f"  {a['account_id']}  {a['name']}")
    print(f"      {a.get('billing_street','')}, {a.get('billing_city','')} "
          f"{a.get('billing_state','')} {a.get('billing_zip','')}")
    print(f"      parent : {a.get('parent_name') or '(none)'}")
    print(f"      status : {a.get('status')}   care: {a.get('care_type')}")
    print(f"      revenue: ${float(a.get('lifetime_revenue') or 0):,.0f}   "
          f"AR: ${float(a.get('outstanding_ar') or 0):,.0f}")
    print()
