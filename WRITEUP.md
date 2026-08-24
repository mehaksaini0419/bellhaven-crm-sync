# Bellhaven CRM Ownership Sync — Writeup

**Mehak Saini**

Repo: `bellhaven-crm-sync`
Time spent: **~4 hours** (roughly 1h exploring the API and data, 1.5h building,
1.5h reviewing output and fixing what the review exposed)

---

## What it does

Scrapes all 34 Bellhaven communities from the public website, pulls all 121 CRM
accounts through the API, matches them, and proposes corrections. Nothing
reaches the CRM until a human approves it in a local review app.

```
python explore.py    # read-only: what the API actually returns
python pipeline.py   # scrape + pull + match -> proposals.json (writes nothing)
python app.py        # review queue at :5000, approve/reject, writes on approve
python verify.py     # re-pulls the CRM and checks the end state
```

---

## Matching approach

I ranked signals by how much I trust them.

**1. Normalised street address + zip.** The strongest signal by far. Both systems
carry the same physical addresses, just written differently. Normalisation
collapses street types and directionals to one canonical form:

| Website | CRM | Normalised |
| --- | --- | --- |
| 1250 NW Franklin Street | 1250 Northwest Franklin St | `1250 nw franklin st` |
| 3313 Wilmington Pike | 3313 Wilmington Pk | `3313 wilmington pk` |
| 805 Colegate Dr | 805 Colegate Drive | `805 colegate dr` |

**2. City + state + name similarity ≥ 0.86.** Catches rebrands and drift where
addresses differ. Name normalisation lowercases, maps `centre→center`,
`rehabilitation→rehab`, and drops filler (`the`, `at`, `of`).

**3. City + state + similarity 0.60–0.86.** Surfaced for a human, never applied.

**Phone is deliberately not a match key.** The same facility carries different
numbers in each system — Findlay is (231) 533-2969 on the website and
(330) 975-2492 in the CRM. Matching on it would have produced false negatives.

---

## What it found

| Type | Count |
| --- | --- |
| Name / parent corrections | 10 |
| Duplicates marked | 7 |
| New accounts created | 4 |
| CHOW re-parents | 2 |
| Flagged for human review | 4 |

Bellhaven's hierarchy went from **29 children to 38**, and every one of the 34
website communities now resolves to an account under the Bellhaven parent.

---

## The judgment calls

**The CHOW rule.** Two facilities — Tiffin ($84,000 revenue, $12,400 AR) and
Marietta ($51,250 / $3,800) — sat under Cedar Trail while the website listed
them as Bellhaven. Both had revenue *and* outstanding AR, so the SOP forbids
re-parenting. The pipeline creates a successor under Bellhaven, leaves the old
record's `parent_id` untouched, and links them with `chow_current_account`.
`verify.py` asserts both conditions explicitly.

The other wrongly-parented accounts (Lima, Zanesville, Kettering, Port Clinton,
Erie, Monroe, Findlay) had no AR, so they were re-parented directly. Findlay is
the one worth noting: $22,000 lifetime revenue but **zero** AR, so it takes the
direct path — the SOP requires both conditions, not either.

**Same address ≠ duplicate.** Sandusky has two accounts at 2715 Columbus Ave:
Bellhaven's ($130,000 revenue) and Millstone Care of Sandusky's ($0). The
facility is **not on the Bellhaven website**. Read together, that says
divestiture, not duplication — Bellhaven likely sold it and Millstone opened
their own record. Deactivating Millstone's account would have been a real error.
So the rule became: only propose a merge when the website confirms Bellhaven
still owns the address. Otherwise flag the cluster and ask.

**Which record survives a merge.** My first version tie-broke on account ID,
which picked a competitor's record over Bellhaven's at Monroe, Port Clinton and
Erie — it would have deactivated the correct account. Survivor order is now:
most revenue, then AR, then already under the confirmed parent, then any parent,
then ID for determinism.

**Superseded records must not win matches.** After a CHOW, two accounts sit at
one address. The old one has more revenue, so `pick_survivor` kept selecting it
and the successor looked unmatched. Any account with `chow_current_account` set
is retired by definition and is now excluded from matching and from the
not-on-website check.

**Amberly Manor.** On Bellhaven's website in Hudson, OH; the CRM already has an
"Amberly Manor" in Colorado Springs under Juniper Point. Different address, so
a different facility — "Amberly" is a Stonebridge/Juniper naming convention, so
this reads as an acquisition Bellhaven hasn't rebranded. Created as new, with a
note naming the other record so a future reviewer doesn't mistake them for
duplicates.

---

## Re-runs are safe

Every proposal carries a fingerprint hashed from its type, target account and
exact change. Decisions live in SQLite; the pipeline filters out anything
already decided.

Two things make this hold in practice:

- **CHOW pairs are exempt from duplicate detection.** Otherwise every run would
  try to undo the previous run's CHOW.
- **No-op proposals are pruned.** If the CRM already says what the proposal
  wants it to say, it isn't proposed. Without this, a cosmetic difference (a
  survivor renamed after its duplicate note was written) resurfaces decided
  items forever.

After the final run: **0 proposals.** The system has converged.

---

## How I used AI

Heavily, and as a collaborator rather than a code generator.

**Where it helped most:** drafting the scaffolding — API client, scraper,
Flask review app — so I could spend my time on the matching rules and the
data itself rather than boilerplate.

**Where I had to correct it:** the first client guessed the API returned
`items` and an `id` field. It actually returns `data` and `account_id`. I caught
that by writing `explore.py` first and reading the real response before trusting
any assumption — that turned out to be the single most useful thing I did.

**Where my own review mattered more than the tooling:** every issue in the
"judgment calls" section above came out of reading the proposals before
approving them, not from the code being clever. The Chesterton and Kettering
address-normalisation gaps, the survivor-selection bug, and the Sandusky
divestiture were all found by checking output against the CRM by hand with
`lookup.py`.

That loop — generate, inspect, find the wrong thing, tighten the rule, re-run —
is the whole method. The first run produced 21 proposals; the version I approved
produced 27, several of which the first version had wrong.

---

## What I'd build next

**Confidence-tiered auto-approval.** Exact address matches with a single
candidate are safe to apply without review. Reserve human attention for the
ambiguous middle. Right now everything queues equally, which won't scale past a
few operators.

**Change history, not just current state.** The CRM is a point-in-time snapshot.
An append-only log of what changed, when, and on what evidence would let you
answer "why is this account under Bellhaven?" six months from now.

**Treat the website as one source among several.** State licensing databases and
CMS provider files would corroborate ownership independently. A single scraped
page is a thin basis for deactivating a revenue-bearing account.

**Alert on the shape of a run, not just its contents.** If a run suddenly
proposes 60 changes instead of 5, the website template probably changed and the
scraper is producing garbage. That should page someone before it reaches a
review queue.

**Contacts.** The API exposes them and I didn't touch them. When a facility
changes hands the administrator usually changes too, and stale contacts are how
reps end up calling the wrong person.
