"""Reopen decisions for one account so the pipeline can re-propose them.

Used after a rule change: the stored decision reflects the old logic, and we
want the corrected pipeline to surface a fresh proposal for a human to review
rather than patching the CRM by hand.

    python reopen.py 001SXSF4ELF0Z2LGDM
"""
import json
import sqlite3
import sys
import config

if len(sys.argv) < 2:
    raise SystemExit("usage: python reopen.py <account_id>")

target = sys.argv[1]
conn = sqlite3.connect(config.DECISIONS_DB)
rows = conn.execute("SELECT fp, decision, proposal FROM decisions").fetchall()

removed = 0
for fp, decision, blob in rows:
    p = json.loads(blob)
    if p.get("account_id") == target:
        print(f"  reopening  {p['type']:26} ({decision})")
        conn.execute("DELETE FROM decisions WHERE fp = ?", (fp,))
        removed += 1

conn.commit()
conn.close()
print(f"\n{removed} decision(s) reopened for {target}.")
print("Run `python pipeline.py`, then approve in the review app.")
