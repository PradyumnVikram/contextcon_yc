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
DB_PATH = Path(os.getenv("CLEARANCE_DB", ROOT / "clearance.db"))
MAILBOX_DIR = Path(os.getenv("CLEARANCE_MAILBOX", ROOT / "mailbox"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CRUSTDATA_API_KEY = os.getenv("CRUSTDATA_API_KEY", "")

# --- Claude (Person B) -------------------------------------------------------
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

# --- Screening (§4.2) --------------------------------------------------------
SCREEN_WEIGHTS = {"token_set": 0.60, "jaro_winkler": 0.25, "address": 0.15}
SCREEN_EXACT_SCORE = 97
SCREEN_FUZZY_SCORE = 85
NAME_SUFFIXES = ["pvt ltd", "private limited", "pvt. ltd.", "llc", "limited", "ltd", "inc", "co"]
FORWARDER_KEYWORDS = ["freight", "logistics", "cargo", "forwarding", "shipping", "courier"]

# --- Buyer type (§4.4) -------------------------------------------------------
DISTRIBUTOR_KEYWORDS = ["trading", "wholesale", "distribution", "distributor", "import", "export house"]
MANUFACTURER_KEYWORDS = ["manufacturer", "manufacturing", "laboratory", "design", "radar", "telecom equipment"]
PEOPLE_VOTE_MANUFACTURER_ENG_SHARE = 0.30
PEOPLE_VOTE_DISTRIBUTOR_SALES_OPS_SHARE = 0.60
PEOPLE_VOTE_DISTRIBUTOR_MAX_ENG_SHARE = 0.10

# --- Capability scoring (§4.6) -----------------------------------------------
TRANSSHIPMENT_HUBS = ["AE", "HK", "TR", "SG"]  # ISO-3166 alpha-2
LOW_PERCENTILE = 10

CAPABILITY_POINTS = {
    "C1_no_matching_people": 40,
    "C2_low_engineering_share": 20,
    "C3_young_company": 15,
    "C4_headcount_decline": 10,
    "C5_low_traffic": 10,
    "O1_units_per_engineer": 20,
    "O2_transshipment_hub": 15,
    "O3_ship_to_mismatch": 5,
    "D1_young_distributor": 25,
    "D2_small_distributor": 15,
    "D3_low_traffic_distributor": 15,
    "D4_large_order_small_distributor": 15,
}
YOUNG_COMPANY_YEARS = 2
YOUNG_DISTRIBUTOR_YEARS = 3
HEADCOUNT_DECLINE_PCT = 20
SMALL_DISTRIBUTOR_HEADCOUNT = 20

TIER_MEDIUM_MIN = 30
TIER_HIGH_MIN = 60

# --- End-use (§4.7) ----------------------------------------------------------
END_USE_MAX_FOLLOWUPS = 1
ORDER_DETAILS_MAX_ROUNDS = 1
VAGUE_USE_PHRASES = ["civilian use", "civil use", "general use", "commercial use", ""]

# --- Destinations (§4.1) -----------------------------------------------------
DESTINATIONS = ["IN", "AE", "HK", "TR", "SG", "DE", "US", "RU", "CN"]
