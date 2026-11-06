"""All tunable values in one place. SHARED FILE: changes need both teammates (see WORKFLOW.md §6).

Every weight and threshold from AGENTS_*.md §4 lives here, so tuning never touches module code.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _repo_path(value: str | Path) -> Path:
    """Relative paths in .env resolve against the repo root, so every window shares the same files
    no matter which directory it was started from."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else ROOT / p


DB_PATH = _repo_path(os.getenv("CLEARANCE_DB", "clearance.db"))
MAILBOX_DIR = _repo_path(os.getenv("CLEARANCE_MAILBOX", "mailbox"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CRUSTDATA_API_KEY = os.getenv("CRUSTDATA_API_KEY", "")

# --- LLM (Person B) ----------------------------------------------------------
# "ollama" (default): local model, nothing leaves the machine. "claude": Anthropic API (needs ANTHROPIC_API_KEY).
LLM_PROVIDER = os.getenv("CLEARANCE_LLM", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")   # fits an 8 GB GPU at Q4
OLLAMA_TIMEOUT_S = 180.0
OLLAMA_NUM_CTX = 8192

LLM_MODEL = "claude-opus-5-5"
LLM_MAX_TOKENS = 16000
LLM_SERVER_FALLBACK = True  # server-side refusal fallback (`fallbacks: "default"`); set False if the API rejects it
LLM_EFFORT = {
    "parse_order": "low",
    "extract_end_use": "low",
    "map_needs": "low",
    "draft_email": "medium",
    "explain": "medium",
}

# --- Crustdata (Person A) ----------------------------------------------------
CRUSTDATA_BASE_URL = "https://api.crustdata.com"
CRUSTDATA_API_VERSION = "2025-11-01"
CRUSTDATA_ENRICH_PER_MIN = 15
PEOPLE_CAP_PER_COMPANY = 25
PEER_SET_MIN, PEER_SET_MAX = 20, 50
PEER_ENRICH_MAX = 20   # peers enriched in one batch for engineering share + traffic (~2 credits each, cached)
CRUSTDATA_MAX_AGE_DAYS = 7   # cached company, people and peer data older than this is fetched again
SCREENING_LIST_MAX_AGE_DAYS = 7   # older restricted lists are flagged as stale in the evidence and the sidebar
DUPLICATE_ORDER_DAYS = 7     # the same open order re-sent by the same sender within this window joins the first

# --- Screening (§4.2) --------------------------------------------------------
SCREEN_WEIGHTS = {"token_set": 0.60, "jaro_winkler": 0.25, "address": 0.15}
SCREEN_EXACT_SCORE = 97
SCREEN_FUZZY_SCORE = 85
NAME_SUFFIXES = ["pvt ltd", "private limited", "pvt. ltd.", "llc", "limited", "ltd", "inc", "co"]
FORWARDER_KEYWORDS = ["freight", "logistics", "cargo", "forwarding", "shipping", "courier"]

# --- Buyer type (§4.4) -------------------------------------------------------
# Description is a guide, not the decision. "manufacturing" and "design" match industry
# labels (Digi-Key is "Electronics Manufacturing") so they are not manufacturer proof.
DISTRIBUTOR_KEYWORDS = ["trading", "wholesale", "distribution", "distributor", "reseller", "import", "export house"]
MANUFACTURER_KEYWORDS = ["manufactures", "fabrication", "factory", "semiconductor manufacturer"]
PEOPLE_VOTE_MANUFACTURER_ENG_SHARE = 0.30
PEOPLE_VOTE_DISTRIBUTOR_SALES_OPS_SHARE = 0.60
PEOPLE_VOTE_DISTRIBUTOR_MAX_ENG_SHARE = 0.10

# --- Capability scoring (§4.6) -----------------------------------------------
TRANSSHIPMENT_HUBS = ["AE", "HK", "TR", "SG"]  # ISO-3166 alpha-2
# Vishay is about 28% engineering and TE about 31%. Below this, a manufacturer
# with no other evidence of the work takes C1 points.
TECHNICAL_SHARE_CLEAR = 0.25
# C2 fades from this many points at the 0th percentile of peers to 0 points at the 50th.
# There is no cliff at the old 10th-percentile line.
C2_FADE_UNTIL = 50

CAPABILITY_POINTS = {
    "C1_not_a_technical_business": 40,
    "C2_low_engineering_share": 20,
    "C3_small_staff": 15,
    "C4_headcount_decline": 10,
    # Tracked against peers, not scored. A small team that orders too much is already C1/O1/D4.
    "C5_low_traffic": 0,
    "O1_quantity_vs_technical_staff": 20,
    # Recorded on the file, not added to the score. A normal distributor ships to these countries.
    "O2_transshipment_hub": 0,
    "O3_ship_to_mismatch": 0,
    "D1_small_staff": 25,
    "D2_small_distributor": 0,
    "D3_low_traffic_distributor": 0,
    "D4_large_order_small_distributor": 15,
}
# Small-staff points fade to 0 at this headcount. A sample that covers the whole
# company raises them, because we are not missing a hidden engineering team.
SMALL_STAFF_FADE_AT = 80
SMALL_STAFF_SAMPLE_COVERS = 0.7
HEADCOUNT_DECLINE_PCT = 20
# Quantity points reach the full value at this many times a reasonable order.
OVER_ORDER_FULL_AT = 5
# 10,000 high-end parts (5 per technical person) looks normal only around 2,000
# engineers. 10,000 commodity FPGAs (50 per person) looks normal around 200.

TIER_MEDIUM_MIN = 30
TIER_HIGH_MIN = 60

# --- End-use (§4.7) ----------------------------------------------------------
END_USE_MAX_FOLLOWUPS = 1
ORDER_DETAILS_MAX_ROUNDS = 1
VAGUE_USE_PHRASES = ["civilian use", "civil use", "general use", "commercial use", ""]

# --- Destinations (§4.1) -----------------------------------------------------
DESTINATIONS = ["IN", "AE", "HK", "TR", "SG", "DE", "US", "RU", "CN"]
