"""Thin, honest wrapper around the Bellhaven CRM sandbox API.

Every write goes through here so there is exactly one place that can
change data, and every write is logged.
"""
import json
import time
import requests
import config


class CRMClient:
    def __init__(self, token=None, base=config.API):
        token = token or config.API_TOKEN
        if not token:
            # Fail here rather than at import: everything that needs a
            # credential goes through this class, and nothing else should be
            # blocked by its absence.
            raise SystemExit(config.MISSING_TOKEN_MSG)
        self.base = base
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.write_log = []

    # --- reads ----------------------------------------------------------
    def _get(self, path, **params):
        r = self.session.get(f"{self.base}{path}", params=params,
                             timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def list_accounts(self):
        """Page through every account.

        The API returns {"data": [...], "page", "page_size", "total"} and
        names the key field "account_id" (not "id").
        """
        out, page = [], 1
        while True:
            payload = self._get("/accounts", page=page, page_size=50)
            rows = payload.get("data", [])
            out.extend(rows)
            total = payload.get("total", len(out))
            if len(out) >= total or not rows:
                break
            page += 1
            if page > 50:  # hard safety stop
                break
        return out

    def get_account(self, account_id):
        return self._get(f"/accounts/{account_id}")

    def list_contacts(self, account_id=""):
        return self._get("/contacts", account_id=account_id)

    # --- writes ---------------------------------------------------------
    def patch_account(self, account_id, fields, dry_run=False):
        """Update named fields on one account."""
        entry = {"op": "PATCH", "account_id": account_id, "fields": fields,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if dry_run:
            entry["dry_run"] = True
            self.write_log.append(entry)
            return entry
        r = self.session.patch(f"{self.base}/accounts/{account_id}",
                               data=json.dumps(fields),
                               timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        entry["response"] = r.json()
        self.write_log.append(entry)
        return entry["response"]

    def create_account(self, fields, dry_run=False):
        """Create a new account (used by the CHOW path and new locations)."""
        entry = {"op": "POST", "fields": fields,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if dry_run:
            entry["dry_run"] = True
            self.write_log.append(entry)
            return entry
        r = self.session.post(f"{self.base}/accounts",
                              data=json.dumps(fields),
                              timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        entry["response"] = r.json()
        self.write_log.append(entry)
        return entry["response"]
