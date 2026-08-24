"""Match website communities to CRM accounts and classify what to do.

Matching strategy, strongest signal first:
  1. Normalised street address + zip   -> exact identity, highest confidence
  2. City + state + high name similarity
  3. City + state + moderate name similarity -> needs human review, never auto

Phone is deliberately NOT used: the sandbox has different phone numbers on
the website and in the CRM for the same facility, so it is not reliable.
"""
import re
from difflib import SequenceMatcher
import config

# ---------------------------------------------------------------- normalise

_SUFFIX = {
    "center": "center", "centre": "center", "ctr": "center",
    "rehabilitation": "rehab", "rehab": "rehab",
    "healthcare": "health care", "health": "health", "care": "care",
    "nursing": "nursing", "and": "&",
}
_NOISE = {"the", "at", "of", "llc", "inc", "parent", "account"}


def norm_name(s):
    """Lowercase, expand abbreviations, drop filler words and punctuation."""
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    toks = []
    for t in s.split():
        t = _SUFFIX.get(t, t)
        if t in _NOISE:
            continue
        toks.append(t)
    return " ".join(toks)


# Street-type and directional abbreviations. Both sources use different
# conventions for the same address, e.g.
#   CRM     "1250 Northwest Franklin St"
#   website "1250 NW Franklin Street"
# and "3313 Wilmington Pike" vs "3313 Wilmington Pk". Everything collapses to
# one canonical short form.
_ST_ABBR = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "boulevard": "blvd", "lane": "ln", "court": "ct", "circle": "cir",
    "place": "pl", "terrace": "ter", "parkway": "pkwy", "square": "sq",
    "highway": "hwy", "pike": "pk", "turnpike": "tpke", "trail": "trl",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}


def norm_street(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(_ST_ABBR.get(t, t) for t in s.split())


def addr_key(street, zipc):
    """Canonical address identity: normalised street + zip."""
    ns, nz = norm_street(street), str(zipc or "").strip()
    return f"{ns}|{nz}" if ns and nz else None


def address_clusters(accounts):
    """Group every account by canonical address.

    Duplicates in this CRM are not reliably detectable by name - the same
    facility appears as 'Kettering Care Centre', 'Kettering Nursing &
    Rehabilitation' and 'Kettering Senior Campus' under three different
    parents. Address is what identifies them.
    """
    clusters = {}
    for a in accounts:
        k = addr_key(a.get("billing_street"), a.get("billing_zip"))
        if k:
            clusters.setdefault(k, []).append(a)
    return clusters


def pick_survivor(group, target_parent_id=None):
    """Which record of a duplicate cluster should live.

    1. most lifetime revenue - billing history is the thing worth keeping
    2. then outstanding AR
    3. then a record already under the parent the website confirms owns it.
       Without this the tiebreak is arbitrary and we would keep a competitor's
       record and deactivate the correct one.
    4. then any parent at all (a more complete record)
    5. then lowest account_id, purely so the choice is deterministic
    """
    return sorted(group, key=lambda a: (
        -float(a.get("lifetime_revenue") or 0),
        -float(a.get("outstanding_ar") or 0),
        0 if (target_parent_id and a.get("parent_id") == target_parent_id) else 1,
        0 if a.get("parent_id") else 1,
        a.get("account_id", ""),
    ))[0]


def sim(a, b):
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


# ---------------------------------------------------------------- matching

def match_one(loc, accounts, target_parent_id=None):
    """Return (account_or_None, confidence, reason)."""
    # 1. address + zip
    key = addr_key(loc.get("street"), loc.get("zip"))
    if key:
        hits = [a for a in accounts
                if addr_key(a.get("billing_street"), a.get("billing_zip")) == key]
        # An account with chow_current_account set has been superseded by its
        # successor. It is kept only so billing can chase the old AR, so it must
        # never win a match - the successor is the live relationship.
        live = [a for a in hits if not a.get("chow_current_account")]
        if live:
            hits = live

        if len(hits) == 1:
            return hits[0], 1.0, "exact street address + zip"
        if len(hits) > 1:
            # Several accounts share one address: they are the same facility.
            # Match the website to whichever record we intend to keep, so the
            # rename/re-parent lands on the survivor and not on a record we are
            # about to mark as a duplicate.
            best = pick_survivor(hits, target_parent_id)
            return best, 0.95, (f"exact address match; {len(hits)} accounts share "
                                f"this address (duplicate cluster, survivor selected)")

    # 2. city + state + name similarity
    geo = [a for a in accounts
           if (a.get("billing_city") or "").strip().lower() == (loc.get("city") or "").strip().lower()
           and (a.get("billing_state") or "").strip().upper() == (loc.get("state") or "").strip().upper()]
    if geo:
        scored = sorted(((sim(loc["name"], a.get("name", "")), a) for a in geo),
                        key=lambda x: -x[0])
        top_score, top_acct = scored[0]
        if top_score >= config.NAME_CONFIDENT:
            return top_acct, top_score, f"city+state match, name similarity {top_score:.2f}"
        if top_score >= config.NAME_REVIEW_FLOOR:
            return top_acct, top_score, f"city+state match but name only {top_score:.2f} - needs review"

    return None, 0.0, "no candidate found"


# ---------------------------------------------------------------- classify

def _prune_noops(proposals, by_id):
    """Drop anything that would not actually change the CRM.

    Without this, cosmetic differences (a survivor being renamed after the
    duplicate note was written, say) keep resurfacing decided items forever.
    A proposal should only exist if the CRM does not already say what it wants
    the CRM to say.
    """
    kept = []
    for p in proposals:
        a = p.get("action", {})
        if a.get("op") != "patch":
            kept.append(p)
            continue
        current = by_id.get(p.get("account_id"), {})
        # Compare only substantive fields; free-text notes are not a reason to
        # re-touch a record.
        changed = {k: v for k, v in a["fields"].items()
                   if k != "note" and (current.get(k) or "") != (v or "")}
        if not changed:
            continue
        kept.append(p)
    return kept


def classify(website_rows, accounts, bellhaven_parent_id):
    """Produce a list of proposal dicts. Nothing is written here."""
    proposals = []
    matched_ids = set()

    by_id = {a["account_id"]: a for a in accounts}

    for loc in website_rows:
        if "error" in loc:
            continue
        acct, conf, reason = match_one(loc, accounts, bellhaven_parent_id)

        if acct is None:
            # Does an account elsewhere already carry this exact name? If so the
            # new record needs a note, or a reviewer will later mistake the two
            # for duplicates.
            namesakes = [a for a in accounts
                         if norm_name(a.get("name", "")) == norm_name(loc["name"])]
            note = f"Created from Bellhaven website sync ({loc.get('url','')})."
            extra_evidence = []
            if namesakes:
                where = "; ".join(
                    f"{a['account_id']} in {a.get('billing_city')}, {a.get('billing_state')} "
                    f"under {a.get('parent_name') or 'no parent'}" for a in namesakes)
                note += (f" NOTE: name also used by {where}. Different facility "
                         f"(different address) - not a duplicate.")
                extra_evidence.append(
                    f"Name '{loc['name']}' already exists elsewhere in CRM: {where}. "
                    "Different address, so treated as a distinct facility - likely an "
                    "acquisition not yet rebranded.")

            proposals.append({
                "type": "create_missing_account",
                "website_name": loc["name"],
                "website_url": loc.get("url"),
                "confidence": 0.0,
                "evidence": [f"No CRM account found for {loc['name']} "
                             f"({loc.get('city')}, {loc.get('state')})", reason] + extra_evidence,
                "action": {
                    "op": "create",
                    "fields": {
                        "name": loc["name"],
                        "parent_id": bellhaven_parent_id,
                        "status": "Active",
                        "care_type": (loc.get("care_offerings") or [""])[0],
                        "billing_street": loc.get("street"),
                        "billing_city": loc.get("city"),
                        "billing_state": loc.get("state"),
                        "billing_zip": loc.get("zip"),
                        "phone": loc.get("phone"),
                        "note": note,
                    },
                },
            })
            continue

        matched_ids.add(acct["account_id"])
        changes, evidence = {}, [f"Matched on: {reason}"]

        # -- wrong or missing parent -------------------------------------
        if acct.get("parent_id") != bellhaven_parent_id:
            cur = by_id.get(acct.get("parent_id"), {}).get("name", "none")
            evidence.append(f"CRM parent is '{cur}', website lists this as a Bellhaven community")
            rev = float(acct.get("lifetime_revenue") or 0)
            ar = float(acct.get("outstanding_ar") or 0)

            if rev > 0 and ar > 0:
                # SOP: preserve the old account for billing, create a new one
                proposals.append({
                    "type": "chow_reparent",
                    "account_id": acct["account_id"],
                    "account_name": acct.get("name"),
                    "website_name": loc["name"],
                    "confidence": conf,
                    "evidence": evidence + [
                        f"lifetime_revenue ${rev:,.0f} AND outstanding_ar ${ar:,.0f} > 0",
                        "SOP: do NOT re-parent. Create new account under Bellhaven, "
                        "set chow_current_account on the old account.",
                    ],
                    "action": {
                        "op": "chow",
                        "new_account_fields": {
                            "name": loc["name"],
                            "parent_id": bellhaven_parent_id,
                            "status": "Active",
                            "care_type": (loc.get("care_offerings") or [""])[0],
                            "billing_street": loc.get("street"),
                            "billing_city": loc.get("city"),
                            "billing_state": loc.get("state"),
                            "billing_zip": loc.get("zip"),
                            "phone": loc.get("phone"),
                            "note": f"CHOW successor to {acct['account_id']} ({acct.get('name')}).",
                        },
                        "old_account_id": acct["account_id"],
                        "old_account_note": (
                            f"CHOW: facility moved to Bellhaven Senior Living. "
                            f"Old account retained for billing (AR ${ar:,.0f} outstanding)."
                        ),
                    },
                })
                continue
            else:
                changes["parent_id"] = bellhaven_parent_id
                evidence.append(
                    f"lifetime_revenue ${rev:,.0f}, outstanding_ar ${ar:,.0f} "
                    "-> SOP allows direct re-parent"
                )

        # -- name drift ---------------------------------------------------
        if acct.get("name") != loc["name"] and conf >= config.NAME_CONFIDENT:
            changes["name"] = loc["name"]
            evidence.append(f"CRM name '{acct.get('name')}' differs from website '{loc['name']}'")

        # -- reactivate anything the website still lists --------------------
        if acct.get("status") == "Inactive":
            changes["status"] = "Active"
            evidence.append("Account is Inactive in CRM but still listed on the website")

        if changes:
            proposals.append({
                "type": "update_account" if conf >= config.NAME_CONFIDENT else "review_low_confidence",
                "account_id": acct["account_id"],
                "account_name": acct.get("name"),
                "website_name": loc["name"],
                "confidence": conf,
                "evidence": evidence,
                "action": {"op": "patch", "fields": changes},
            })

    # -- duplicates, detected by address across the WHOLE CRM ----------------
    # Not just Bellhaven's children: the same facility can sit under several
    # different parents at once, which is exactly the mess this job exists to
    # clean up.
    website_addr_keys = {addr_key(l.get("street"), l.get("zip"))
                         for l in website_rows if "error" not in l}

    # A CHOW pair deliberately leaves two records at one address: the preserved
    # billing account and its successor. They are not duplicates and must never
    # be proposed as such, or every re-run would try to undo the CHOW.
    chow_linked = set()
    for a in accounts:
        succ = a.get("chow_current_account")
        if succ:
            chow_linked.add(a["account_id"])
            chow_linked.add(succ)

    dupe_ids = set()
    for key, group in address_clusters(accounts).items():
        if len(group) < 2:
            continue

        # Drop records already accounted for: a CHOW pair deliberately keeps two
        # records at one address, and an account already pointing at its
        # survivor is a resolved duplicate. Neither is an open question.
        remaining = [a for a in group
                     if a["account_id"] not in chow_linked
                     and not a.get("duplicate_of_account")]
        if len(remaining) < 2:
            continue
        group = remaining

        if key not in website_addr_keys:
            # Bellhaven does not list this address. Two records at one address
            # where the website is silent is more likely a change of ownership
            # (we sold it, the buyer has their own account) than a duplicate.
            # Deactivating the other operator's record would be wrong, so flag
            # the whole cluster and let a human decide.
            for a in group:
                if a.get("parent_id") != bellhaven_parent_id:
                    continue
                proposals.append({
                    "type": "review_ownership_cluster",
                    "account_id": a["account_id"],
                    "account_name": a.get("name"),
                    "confidence": 0.5,
                    "evidence": [
                        f"{len(group)} accounts share {a.get('billing_street')}, "
                        f"{a.get('billing_city')} {a.get('billing_state')}: "
                        + "; ".join(f"{x.get('name')} (parent: {x.get('parent_name') or 'none'}, "
                                    f"revenue ${float(x.get('lifetime_revenue') or 0):,.0f})"
                                    for x in group),
                        "This address is NOT on the Bellhaven website.",
                        "Same address under different parents with no website listing reads as "
                        "a change of ownership, not a duplicate. Not proposing a merge - "
                        "confirm whether Bellhaven divested this facility.",
                    ],
                    "action": {"op": "patch", "fields": {
                        "status": "Needs Review",
                        "note": "Shares an address with an account under a different parent and "
                                "is not listed on the Bellhaven website. Possible divestiture - "
                                "confirm ownership before billing or outreach.",
                    }},
                })
            continue

        survivor = pick_survivor(group, bellhaven_parent_id)
        for loser in group:
            if loser["account_id"] == survivor["account_id"]:
                continue
            dupe_ids.add(loser["account_id"])
            proposals.append({
                "type": "mark_duplicate",
                "account_id": loser["account_id"],
                "account_name": loser.get("name"),
                "confidence": 0.95,
                "evidence": [
                    f"'{loser.get('name')}' shares an address with "
                    f"'{survivor.get('name')}': {loser.get('billing_street')}, "
                    f"{loser.get('billing_city')} {loser.get('billing_state')} "
                    f"{loser.get('billing_zip')}",
                    f"{len(group)} accounts sit at this address: "
                    + "; ".join(f"{a.get('name')} (parent: {a.get('parent_name') or 'none'})"
                                for a in group),
                    f"Survivor {survivor['account_id']} chosen on revenue "
                    f"${float(survivor.get('lifetime_revenue') or 0):,.0f} / AR "
                    f"${float(survivor.get('outstanding_ar') or 0):,.0f}",
                    "No merge/delete in this API: mark loser Inactive + duplicate_of_account",
                ],
                "action": {"op": "patch", "fields": {
                    "duplicate_of_account": survivor["account_id"],
                    "status": "Inactive",
                    "note": f"Duplicate of {survivor['account_id']} ({survivor.get('name')}). "
                            f"Same address, different record.",
                }},
            })

    # -- in CRM under Bellhaven but no longer on the website ------------------
    superseded = {a["account_id"] for a in accounts if a.get("chow_current_account")}
    # An account already flagged as a possible divestiture says the same thing
    # more precisely; do not raise a second, vaguer flag on the same record.
    flagged = {p["account_id"] for p in proposals
               if p["type"] == "review_ownership_cluster"}
    for a in accounts:
        if a["account_id"] in superseded or a["account_id"] in flagged:
            continue  # retired by a CHOW, or already flagged with better evidence
        if a.get("duplicate_of_account") or a.get("status") == "Inactive":
            continue  # a retired record is not "missing from the website"
        if a.get("parent_id") != bellhaven_parent_id:
            continue
        if a["account_id"] in matched_ids or a["account_id"] in dupe_ids:
            continue
        proposals.append({
            "type": "not_on_website",
            "account_id": a["account_id"],
            "account_name": a.get("name"),
            "confidence": 0.7,
            "evidence": [
                f"'{a.get('name')}' ({a.get('billing_city')}, {a.get('billing_state')}) "
                "sits under Bellhaven in CRM but no matching community on the website",
                "Could be divested, closed, or simply not listed. Flag for a human, do not guess.",
            ],
            "action": {"op": "patch", "fields": {
                "status": "Needs Review",
                "note": "Not found on Bellhaven website during sync - confirm ownership.",
            }},
        })

    return _prune_noops(proposals, by_id)
