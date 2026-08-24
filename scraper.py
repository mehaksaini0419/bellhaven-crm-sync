"""Scrape every Bellhaven community from the public website.

The listing pages give name / city / state / one care type.
The detail pages give the full street address, zip, all care offerings,
administrator and phone. We follow every detail page because the street
address is our strongest matching key.
"""
import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
import config


def _soup(url):
    r = requests.get(url, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _listing_slugs():
    """Walk the paginated directory and collect every community slug."""
    slugs, page = [], 1
    while True:
        s = _soup(f"{config.SITE}/communities?page={page}")
        found = [a["href"] for a in s.select('a[href^="/communities/"]')]
        found = [h for h in found if h != "/communities"]
        if not found:
            break
        slugs.extend(found)
        nxt = s.find("a", string=re.compile("Next"))
        if not nxt:
            break
        page += 1
        if page > 25:  # safety
            break
        time.sleep(config.POLITE_DELAY_SEC)
    # de-duplicate, preserve order
    seen, out = set(), []
    for h in slugs:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _field(soup, label):
    """Detail pages render as <label> then value. Find the block by label."""
    node = soup.find(string=re.compile(rf"^\s*{re.escape(label)}\s*$"))
    if not node:
        return ""
    parent = node.find_parent()
    if not parent:
        return ""
    sib = parent.find_next_sibling()
    return sib.get_text("\n", strip=True) if sib else ""


def _parse_detail(slug):
    url = f"{config.SITE}{slug}"
    s = _soup(url)
    name = s.find("h1").get_text(strip=True)

    addr_raw = _field(s, "Address")
    lines = [l.strip() for l in addr_raw.split("\n") if l.strip()]
    street = lines[0] if lines else ""
    city = state = zipc = ""
    if len(lines) > 1:
        m = re.match(r"(.+),\s*([A-Z]{2})\s+(\d{5})", lines[-1])
        if m:
            city, state, zipc = m.group(1).strip(), m.group(2), m.group(3)

    care_raw = _field(s, "Care Offerings")
    # offerings run together in the markup: split on the capital that starts a new one
    care = re.findall(r"[A-Z][a-z]+(?:[ &\-][A-Za-z]+)*", care_raw)

    return {
        "source": "website",
        "slug": slug,
        "url": url,
        "name": name,
        "street": street,
        "city": city,
        "state": state,
        "zip": zipc,
        "care_offerings": care,
        "administrator": _field(s, "Administrator"),
        "phone": _field(s, "Phone"),
    }


def scrape(save=True):
    slugs = _listing_slugs()
    rows = []
    for slug in slugs:
        try:
            rows.append(_parse_detail(slug))
        except Exception as e:  # a single bad page must not kill the run
            rows.append({"source": "website", "slug": slug, "error": str(e)})
        time.sleep(config.POLITE_DELAY_SEC)
    if save:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(config.SCRAPE_FILE, "w") as f:
            json.dump(rows, f, indent=2)
    return rows


if __name__ == "__main__":
    data = scrape()
    ok = [r for r in data if "error" not in r]
    print(f"scraped {len(ok)} communities ({len(data) - len(ok)} errors)")
    for r in ok[:5]:
        print(" ", r["name"], "|", r["street"], "|", r["city"], r["state"], r["zip"])
