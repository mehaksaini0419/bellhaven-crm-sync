"""Orchestrator: scrape -> pull CRM -> match -> write proposals.json

Writes NOTHING to the CRM. Proposals only. Approval happens in app.py.
"""
import json
import os
import sys
import config
import scraper
import store
from crm_client import CRMClient
from matcher import classify


def find_bellhaven_parent(accounts):
    for a in accounts:
        if a.get("name") == config.BELLHAVEN_PARENT_NAME:
            return a["account_id"]
    for a in accounts:
        n = (a.get("name") or "").lower()
        if "bellhaven" in n and "parent" in n:
            return a["account_id"]
    raise SystemExit("Could not find the Bellhaven parent account.")


def run(skip_scrape=False):
    # Check the credential before doing 30 seconds of scraping we would only
    # have to throw away.
    if not config.API_TOKEN:
        raise SystemExit(config.MISSING_TOKEN_MSG)

    os.makedirs(config.DATA_DIR, exist_ok=True)

    # 1. website
    if skip_scrape and os.path.exists(config.SCRAPE_FILE):
        website = json.load(open(config.SCRAPE_FILE))
        print(f"[1/4] reusing {len(website)} scraped communities")
    else:
        print("[1/4] scraping website...")
        website = scraper.scrape()
        print(f"      {len(website)} communities")

    # 2. CRM
    print("[2/4] pulling CRM accounts...")
    crm = CRMClient()
    accounts = crm.list_accounts()
    json.dump(accounts, open(config.CRM_FILE, "w"), indent=2, default=str)
    print(f"      {len(accounts)} accounts")

    parent_id = find_bellhaven_parent(accounts)
    print(f"      Bellhaven parent id: {parent_id}")

    # 3. match + classify
    print("[3/4] matching...")
    proposals = classify(website, accounts, parent_id)

    # 4. drop anything a human already decided
    decided = store.already_decided()
    fresh = []
    for p in proposals:
        p["fingerprint"] = store.fingerprint(p)
        if p["fingerprint"] in decided:
            continue
        fresh.append(p)

    json.dump(fresh, open(config.PROPOSALS_FILE, "w"), indent=2, default=str)
    print(f"[4/4] {len(proposals)} proposals, {len(proposals) - len(fresh)} already decided, "
          f"{len(fresh)} open")

    counts = {}
    for p in fresh:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"      {v:3d}  {k}")
    return fresh


if __name__ == "__main__":
    run(skip_scrape="--skip-scrape" in sys.argv)
