"""Central configuration. Everything tunable lives here, nothing is hardcoded elsewhere."""
import os

# --- API / site ---------------------------------------------------------
# The token is never hardcoded. It is also not demanded at import time: the
# matching logic and its tests are pure functions that never touch the API, and
# a reviewer cloning this repo should be able to run the test suite without
# holding a credential. The check lives in CRMClient, at the point of use.
API_TOKEN = os.environ.get("BELLHAVEN_TOKEN")

MISSING_TOKEN_MSG = (
    "BELLHAVEN_TOKEN is not set. Export it before running anything that talks "
    "to the CRM, e.g.\n"
    "  bash:       export BELLHAVEN_TOKEN=bh_...\n"
    "  PowerShell: $env:BELLHAVEN_TOKEN = 'bh_...'\n"
    "See .env.example."
)

BASE = "https://analyst-assessment-production.up.railway.app"
API = f"{BASE}/api/v1"
SITE = BASE

# The parent account every Bellhaven community should sit under.
BELLHAVEN_PARENT_NAME = "Bellhaven Senior Living (Parent Account)"

# --- Matching thresholds ------------------------------------------------
# Name similarity (0-1) required to call a name-based match confident,
# once city+state already agree.
NAME_CONFIDENT = 0.86
# Below this we do not propose anything automatically; a human decides.
NAME_REVIEW_FLOOR = 0.60

# --- Files --------------------------------------------------------------
DATA_DIR = "data"
SCRAPE_FILE = f"{DATA_DIR}/website_locations.json"
CRM_FILE = f"{DATA_DIR}/crm_accounts.json"
PROPOSALS_FILE = f"{DATA_DIR}/proposals.json"
DECISIONS_DB = f"{DATA_DIR}/decisions.db"

# --- Behaviour ----------------------------------------------------------
REQUEST_TIMEOUT = 30
POLITE_DELAY_SEC = 0.15  # between website page fetches
