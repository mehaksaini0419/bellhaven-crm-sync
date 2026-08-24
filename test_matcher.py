"""Tests for the matching and classification rules.

Every test here exists because something went wrong during the build. They are
regression tests, not decoration: each one pins down a decision that was made
after seeing real data behave badly.

    python test_matcher.py
"""
import matcher
from matcher import addr_key, norm_name, pick_survivor, classify

PARENT = "PARENT_BELLHAVEN"
OTHER = "PARENT_CEDAR"

_passed, _failed = 0, 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")


def acct(aid, name, parent=PARENT, street="1 Main St", zipc="10001",
         city="Town", state="OH", rev=0, ar=0, status="Active", **kw):
    d = {"account_id": aid, "name": name, "parent_id": parent,
         "billing_street": street, "billing_zip": zipc, "billing_city": city,
         "billing_state": state, "lifetime_revenue": rev, "outstanding_ar": ar,
         "status": status, "parent_name": parent}
    d.update(kw)
    return d


def holding(aid, name):
    """A parent/holding-company record.

    These carry no facility address in the real CRM, and that absence is what
    keeps them out of address-based duplicate detection. A facility with no
    parent (Findlay, before this run) is a different thing entirely - it still
    has an address.
    """
    return {"account_id": aid, "name": name, "parent_id": None,
            "billing_street": "", "billing_zip": "", "billing_city": "",
            "billing_state": "", "lifetime_revenue": 0, "outstanding_ar": 0,
            "status": "Active", "parent_name": None}


def site(name, street="1 Main St", zipc="10001", city="Town", state="OH"):
    return {"name": name, "street": street, "zip": zipc, "city": city,
            "state": state, "care_offerings": ["Assisted Living"], "url": "u"}


# ---------------------------------------------------------------------------
print("\nADDRESS NORMALISATION")
print("  (both of these silently broke matching on the first real run)")

check("NW == Northwest",
      addr_key("1250 NW Franklin Street", "46304"),
      addr_key("1250 Northwest Franklin St", "46304"))

check("Pike == Pk",
      addr_key("3313 Wilmington Pike", "45429"),
      addr_key("3313 Wilmington Pk", "45429"))

check("Drive == Dr",
      addr_key("805 Colegate Drive", "45750"),
      addr_key("805 Colegate Dr", "45750"))

check("different zip is a different place",
      addr_key("1 Main St", "10001") == addr_key("1 Main St", "10002"),
      False)

print("\nNAME NORMALISATION")
check("Centre == Center",
      norm_name("Bellhaven Healthcare Centre of Ashland"),
      norm_name("Bellhaven Health Care Center of Ashland"))
check("'at' and 'of' are filler",
      norm_name("Bellhaven at Sycamore Ridge"),
      norm_name("Bellhaven of Sycamore Ridge"))


# ---------------------------------------------------------------------------
print("\nCHOW SOP  (the rule they said matters as much as matching)")

# revenue AND ar -> must NOT re-parent
props = classify([site("Bellhaven of Tiffin")],
                 [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                  holding(OTHER, "Cedar Trail (Parent Account)"),
                  acct("A", "Bellhaven of Tiffin", OTHER, rev=84000, ar=12400)],
                 PARENT)
chow = [p for p in props if p["type"] == "chow_reparent"]
check("revenue>0 AND ar>0 triggers CHOW", len(chow), 1)
check("CHOW action is a two-step create+link", chow[0]["action"]["op"], "chow")
check("CHOW never patches parent_id on the old record",
      "parent_id" in str(chow[0]["action"].get("old_account_note", "")), False)
check("CHOW successor goes under Bellhaven",
      chow[0]["action"]["new_account_fields"]["parent_id"], PARENT)

# revenue but NO ar -> direct re-parent (the Findlay case)
props = classify([site("Bellhaven Meadows of Findlay")],
                 [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                  acct("B", "Bellhaven Meadows of Findlay", None, rev=22000, ar=0)],
                 PARENT)
upd = [p for p in props if p["type"] == "update_account"]
check("revenue>0 but ar=0 re-parents directly", len(upd), 1)
check("  and sets parent_id", upd[0]["action"]["fields"].get("parent_id"), PARENT)

# ar but no revenue -> also direct (SOP needs BOTH)
props = classify([site("Bellhaven of Nowhere")],
                 [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                  holding(OTHER, "Cedar Trail (Parent Account)"),
                  acct("C", "Bellhaven of Nowhere", OTHER, rev=0, ar=5000)],
                 PARENT)
check("ar>0 but revenue=0 is NOT a CHOW",
      [p["type"] for p in props].count("chow_reparent"), 0)


# ---------------------------------------------------------------------------
print("\nDUPLICATE SURVIVOR SELECTION")

group = [acct("X", "Competitor Record", OTHER),
         acct("A", "Bellhaven Record", PARENT)]
check("prefers the record under the confirmed parent over a lower id",
      pick_survivor(group, PARENT)["account_id"], "A")

group = [acct("A", "No revenue", PARENT, rev=0),
         acct("B", "Has revenue", OTHER, rev=130000)]
check("revenue beats parent match",
      pick_survivor(group, PARENT)["account_id"], "B")


# ---------------------------------------------------------------------------
print("\nDIVESTITURE IS NOT A DUPLICATE")
print("  (Sandusky: two parents at one address, absent from the website)")

props = classify(
    [site("Bellhaven of Elsewhere", street="9 Other Rd", zipc="99999")],
    [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
     holding("MILL", "Millstone (Parent Account)"),
     acct("S1", "Bellhaven of Sandusky", PARENT, street="2715 Columbus Ave",
          zipc="44870", rev=130000),
     acct("S2", "Millstone Care of Sandusky", "MILL", street="2715 Columbus Ave",
          zipc="44870")],
    PARENT)
types = [p["type"] for p in props]
check("does not propose a merge", types.count("mark_duplicate"), 0)
check("flags the cluster for a human", types.count("review_ownership_cluster"), 1)
check("only one flag per account (no duplicate not_on_website)",
      len([p for p in props if p.get("account_id") == "S1"]), 1)


# ---------------------------------------------------------------------------
print("\nSUPERSEDED RECORDS")
print("  (after a CHOW the old record has more revenue - it must still lose)")

old = acct("OLD", "Bellhaven of Tiffin", OTHER, rev=84000, ar=12400,
           chow_current_account="NEW")
new = acct("NEW", "Bellhaven of Tiffin", PARENT, rev=0)
found, conf, _ = matcher.match_one(site("Bellhaven of Tiffin"),
                                   [old, new], PARENT)
check("website matches the successor, not the retired record",
      found["account_id"], "NEW")

props = classify([site("Bellhaven of Tiffin")],
                 [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                  holding(OTHER, "Cedar Trail (Parent Account)"), old, new],
                 PARENT)
check("CHOW pair is never proposed as a duplicate",
      [p["type"] for p in props].count("mark_duplicate"), 0)
check("retired record is not flagged as missing from the website",
      [p.get("account_id") for p in props].count("OLD"), 0)


# ---------------------------------------------------------------------------
print("\nNO-OP PRUNING")
print("  (a proposal that changes nothing must not exist)")

already = acct("D", "Bellhaven of Owosso", PARENT,
               duplicate_of_account="E", status="Inactive")
survivor = acct("E", "Bellhaven of Owosso", PARENT, rev=100)
props = classify([], [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                      already, survivor], PARENT)
check("already-marked duplicate is not re-proposed",
      [p.get("account_id") for p in props].count("D"), 0)


# ---------------------------------------------------------------------------
print("\nDECOYS")
print("  (same name, different city - must not be matched together)")

props = classify([site("Amberly Manor", street="4390 Darrow Rd", zipc="44236",
                       city="Hudson", state="OH")],
                 [holding(PARENT, "Bellhaven Senior Living (Parent Account)"),
                  acct("AM", "Amberly Manor", OTHER, street="918 S Nevada Ave",
                       zipc="80903", city="Colorado Springs", state="CO")],
                 PARENT)
creates = [p for p in props if p["type"] == "create_missing_account"]
check("creates a new record rather than matching the namesake", len(creates), 1)
check("but records the namesake in the note so nobody merges them later",
      "Colorado Springs" in creates[0]["action"]["fields"]["note"], True)


# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"  {_passed} passed, {_failed} failed")
print("=" * 60)
raise SystemExit(1 if _failed else 0)
