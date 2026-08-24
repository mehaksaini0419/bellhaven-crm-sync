"""Verify the end state of the CRM after approvals.

Re-pulls everything fresh and checks the things that actually matter:
the Bellhaven hierarchy, the CHOW SOP, duplicate handling, and that no
website community is unaccounted for.

    python verify.py
"""
import json
import config
import scraper
from crm_client import CRMClient
from matcher import addr_key, address_clusters

crm = CRMClient()
accounts = crm.list_accounts()
by_id = {a["account_id"]: a for a in accounts}
parent = next(a for a in accounts if a.get("name") == config.BELLHAVEN_PARENT_NAME)
PID = parent["account_id"]

children = [a for a in accounts if a.get("parent_id") == PID]
print("=" * 70)
print("BELLHAVEN HIERARCHY")
print("=" * 70)
print(f"  total accounts in CRM     : {len(accounts)}")
print(f"  under Bellhaven parent    : {len(children)}   (was 29 before the run)")
print(f"  created by this pipeline  : {sum(1 for a in accounts if a.get('created_by_candidate'))}")

print()
print("=" * 70)
print("CHOW SOP CHECK  (revenue > 0 AND AR > 0 -> old record preserved)")
print("=" * 70)
chow = [a for a in accounts if a.get("chow_current_account")]
if not chow:
    print("  none found - expected 2 (Tiffin, Marietta)")
for a in chow:
    succ = by_id.get(a["chow_current_account"])
    ok_parent = a.get("parent_id") != PID          # old record must NOT be moved
    ok_succ = bool(succ) and succ.get("parent_id") == PID
    print(f"  {a['name']}")
    print(f"    old  {a['account_id']}  parent={a.get('parent_name')}  "
          f"rev=${float(a.get('lifetime_revenue') or 0):,.0f}  "
          f"AR=${float(a.get('outstanding_ar') or 0):,.0f}")
    print(f"    new  {a['chow_current_account']}  "
          f"parent={succ.get('parent_name') if succ else 'MISSING'}")
    print(f"    [{'PASS' if ok_parent else 'FAIL'}] old account's parent left untouched")
    print(f"    [{'PASS' if ok_succ  else 'FAIL'}] successor sits under Bellhaven")

print()
print("=" * 70)
print("DUPLICATES")
print("=" * 70)
dupes = [a for a in accounts if a.get("duplicate_of_account")]
print(f"  marked duplicate: {len(dupes)}")
for a in dupes:
    s = by_id.get(a["duplicate_of_account"], {})
    flag = "PASS" if a.get("status") == "Inactive" else "FAIL - not Inactive"
    print(f"    [{flag}] {a['name']:44} -> {s.get('name','?')}")

print()
print("=" * 70)
print("REMAINING ADDRESS COLLISIONS  (should only be resolved pairs)")
print("=" * 70)
# A CHOW pair deliberately leaves the old (preserved-for-billing) record and
# its successor active at the same address. That is correct by design, not
# an open collision - exclude both sides of every CHOW link here.
chow_ids = {a["account_id"] for a in accounts if a.get("chow_current_account")}
chow_ids |= {a["chow_current_account"] for a in accounts if a.get("chow_current_account")}
open_clusters = 0
for key, group in address_clusters(accounts).items():
    active = [a for a in group if a.get("status") == "Active"
              and not a.get("duplicate_of_account")
              and a["account_id"] not in chow_ids]
    if len(active) > 1:
        open_clusters += 1
        print(f"  {len(active)} active accounts at {active[0].get('billing_street')}, "
              f"{active[0].get('billing_city')}:")
        for a in active:
            print(f"      {a['name']} (parent: {a.get('parent_name') or 'none'})")
print(f"  unresolved clusters: {open_clusters}  "
      f"({len(chow_ids)} CHOW-linked accounts excluded as resolved-by-design)")

print()
print("=" * 70)
print("WEBSITE COVERAGE")
print("=" * 70)
site = json.load(open(config.SCRAPE_FILE))
site = [s for s in site if "error" not in s]

# Use the same match logic the pipeline uses, not address alone - some
# communities legitimately match on city+state+name where the two systems
# hold different street addresses for the same facility.
from matcher import match_one
missing = []
for s in site:
    acct, conf, _ = match_one(s, accounts, PID)
    if acct is None or acct.get("parent_id") != PID:
        missing.append((s, acct, conf))

print(f"  communities on website        : {len(site)}")
print(f"  matched to a Bellhaven account: {len(site) - len(missing)}")
if missing:
    print("  NOT under Bellhaven:")
    for s, acct, conf in missing:
        if acct:
            print(f"      {s['name']} ({s['city']}, {s['state']})")
            print(f"        -> matched {acct['name']} [{acct['account_id']}] "
                  f"conf={conf:.2f} parent={acct.get('parent_name') or 'none'}")
            print(f"        website addr: {s.get('street')} {s.get('zip')}")
            print(f"        CRM addr    : {acct.get('billing_street')} {acct.get('billing_zip')}")
        else:
            print(f"      {s['name']} ({s['city']}, {s['state']}) - no CRM match at all")
else:
    print("  every website community is under the Bellhaven parent")

print()
print("=" * 70)
print("STATUS SPREAD")
print("=" * 70)
from collections import Counter
print(" ", dict(Counter(a.get("status") for a in accounts)))
