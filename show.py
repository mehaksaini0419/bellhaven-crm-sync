"""Print the proposal queue in readable form, so you can sanity-check the
matcher before approving anything.

    python show.py              # everything
    python show.py create       # only proposals whose type contains "create"
"""
import json
import sys
import config

props = json.load(open(config.PROPOSALS_FILE))
flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""

shown = 0
for p in props:
    if flt and flt not in p["type"]:
        continue
    shown += 1
    print("=" * 76)
    print(f"{p['type'].upper()}   confidence={p['confidence']:.2f}")
    print(f"  CRM     : {p.get('account_name') or '(none)'}  [{p.get('account_id','-')}]")
    print(f"  Website : {p.get('website_name') or '(none)'}")
    for e in p["evidence"]:
        print(f"    - {e}")
    a = p["action"]
    print(f"  ACTION  : {a['op']}")
    if a["op"] == "patch":
        for k, v in a["fields"].items():
            print(f"            {k} = {v}")
    elif a["op"] == "create":
        f = a["fields"]
        print(f"            NEW: {f['name']}")
        print(f"                 {f['billing_street']}, {f['billing_city']} "
              f"{f['billing_state']} {f['billing_zip']}")
    elif a["op"] == "chow":
        f = a["new_account_fields"]
        print(f"            1) CREATE {f['name']} under Bellhaven")
        print(f"            2) PATCH  {a['old_account_id']} -> chow_current_account")
        print(f"               (old account's parent_id is NOT touched)")
print("=" * 76)
print(f"{shown} shown, {len(props)} total")
