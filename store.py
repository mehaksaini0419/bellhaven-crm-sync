"""Decision store - this is what makes re-runs safe.

Every proposal gets a stable fingerprint built from what it would change.
Once a human approves or rejects that fingerprint, the pipeline will never
surface it again. Change the underlying facts and the fingerprint changes,
so a genuinely new situation does get re-proposed.
"""
import hashlib
import json
import os
import sqlite3
import time
import config


def fingerprint(p):
    """Stable id for a proposal: type + target + the exact change."""
    basis = {
        "type": p.get("type"),
        "account_id": p.get("account_id"),
        "website_name": p.get("website_name"),
        "action": p.get("action"),
    }
    blob = json.dumps(basis, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _conn():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    c = sqlite3.connect(config.DECISIONS_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS decisions (
        fp TEXT PRIMARY KEY,
        decision TEXT NOT NULL,
        proposal TEXT NOT NULL,
        result TEXT,
        decided_at TEXT NOT NULL
    )""")
    return c


def already_decided():
    with _conn() as c:
        return {r[0] for r in c.execute("SELECT fp FROM decisions")}


def record(p, decision, result=None):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?)",
            (fingerprint(p), decision, json.dumps(p, default=str),
             json.dumps(result, default=str) if result else None,
             time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )


def history():
    with _conn() as c:
        rows = c.execute(
            "SELECT fp, decision, proposal, decided_at FROM decisions ORDER BY decided_at DESC"
        ).fetchall()
    return [{"fp": r[0], "decision": r[1], "proposal": json.loads(r[2]),
             "decided_at": r[3]} for r in rows]
