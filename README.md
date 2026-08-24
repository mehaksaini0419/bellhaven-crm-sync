# Bellhaven CRM Ownership Sync

Keeps the CRM's picture of which parent company owns each Bellhaven facility
accurate, by reconciling the public Bellhaven website against the CRM daily.

Nothing reaches the CRM without a human approving it.

## Run it

```bash
pip install -r requirements.txt

# set your token (see .env.example) - never hardcode it
export BELLHAVEN_TOKEN=bh_...          # PowerShell: $env:BELLHAVEN_TOKEN = 'bh_...'

python pipeline.py     # scrape + pull CRM + build proposals (writes nothing)
python app.py          # review queue at http://127.0.0.1:5000 - approve/reject here
python verify.py       # re-pulls the CRM and checks the end state
```

`pipeline.py` is read-only. `app.py` is the only thing that writes, and only
on an explicit Approve click.

## How matching works

Signals, strongest first:

1. **Normalised street address + zip.** Website and CRM share exact street
   addresses, so this is an identity match.
2. **City + state + name similarity ≥ 0.86.** Handles name drift
   ("Bellhaven Healthcare Centre of Ashland" vs "Bellhaven Health Care Center
   of Ashland", "at Sycamore Ridge" vs "of Sycamore Ridge").
3. **City + state + similarity 0.60–0.86.** Surfaced as
   `review_low_confidence` — never applied automatically.

Name normalisation lowercases, expands abbreviations (`centre`→`center`,
`rehabilitation`→`rehab`), and drops filler (`the`, `at`, `of`).

**Phone is deliberately not a match key.** The same facility carries different
phone numbers on the website and in the CRM, so matching on it would produce
false negatives.

## Proposal types

| Type | Meaning |
| --- | --- |
| `update_account` | Confident match; parent, name or status needs correcting |
| `chow_reparent` | Parent is wrong **and** the SOP forbids re-parenting (see below) |
| `create_missing_account` | On the website, absent from the CRM |
| `mark_duplicate` | Several accounts at one address, and the website confirms Bellhaven owns it |
| `review_ownership_cluster` | Several accounts at one address, but the website does *not* list it — reads as a divestiture, so no merge is proposed |
| `not_on_website` | Under Bellhaven in CRM, no longer listed on the site |
| `review_low_confidence` | Plausible match below the confidence bar |

## The CHOW rule

When an account needs to move to a different parent, `lifetime_revenue` and
`outstanding_ar` decide how:

- **revenue > 0 AND outstanding AR > 0** → billing needs the old account
  preserved. Leave it exactly as it is (parent untouched), create a new account
  under the correct parent, and set `chow_current_account` on the old account
  to the new id.
- **otherwise** → re-parent the existing account directly.

This is enforced in `matcher.py`, and the two-step write is in
`app.py:apply_action`.

## Duplicates

**Detected by address, not by name.** The same facility appears in this CRM as
"Kettering Care Centre", "Kettering Nursing & Rehabilitation" and "Kettering
Senior Campus" under three different parents. No name-based rule finds that;
the shared address does.

The API has no merge or delete, so the loser gets `duplicate_of_account`
pointing at the survivor and `status = Inactive`, with a note explaining why.

**Survivor order:** most lifetime revenue, then outstanding AR, then whichever
record already sits under the parent the website confirms, then any parent at
all, then lowest account id for determinism. The third rule matters — without
it the tie-break is arbitrary, and at Monroe, Port Clinton and Erie it would
have kept a competitor's record and deactivated the correct one.

**Same address is not always a duplicate.** Where several accounts share an
address that the website does *not* list, that reads as a change of ownership —
Bellhaven sold the facility and the buyer opened their own record. Merging would
deactivate the new owner's account. Those clusters are flagged
(`review_ownership_cluster`), never merged.

## Re-runs are safe

Every proposal gets a fingerprint hashed from its type, target account and the
exact change it would make. Approvals and rejections are stored in
`data/decisions.db`, and `pipeline.py` filters out anything already decided.

Re-running changes nothing that was already handled. If the underlying facts
change, the fingerprint changes, and it comes back for a fresh look — which is
the behaviour you want.

## Scheduling

`.github/workflows/daily.yml` runs the pipeline at 07:00 ET daily and publishes
the queue as an artifact. Equivalent cron:

```cron
0 7 * * *  cd /opt/bellhaven-crm-sync && /usr/bin/python3 pipeline.py
```

The scheduled job only builds proposals. Approval stays human.

## Layout

```
config.py       thresholds, URLs, token - all tunables in one place
scraper.py      website -> structured locations
crm_client.py   API wrapper; the only module that can write
matcher.py      normalisation, matching, classification
store.py        decision fingerprints (sqlite) - idempotency
pipeline.py     orchestration, read-only
app.py          review UI + the approved-write path
```
