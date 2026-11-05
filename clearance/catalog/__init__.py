"""Part classification and licence rules (task A4). OWNER: Person A.

data/catalog.csv: one row per known part (DEMO parts, modelled on real control entries).
data/licence_rules.csv: (regime, match, destination) -> required/reason/documents. Most specific row wins:
exact destination beats "*", and for EAR a longer ECCN prefix beats a shorter one.
A part not in the catalog is never guessed: found=False, and the decision table holds the order (R2).
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from clearance import config
from clearance.evidence import Ledger
from clearance.models import Classification, LicenceResult

CATALOG_CSV = config.DATA_DIR / "catalog.csv"
RULES_CSV = config.DATA_DIR / "licence_rules.csv"


def _bool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes")


@lru_cache(maxsize=4)
def load_catalog(path: Path = CATALOG_CSV) -> dict[str, dict]:
    with open(path, newline="") as f:
        return {r["part_number"].strip().upper(): r for r in csv.DictReader(f)}


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_CSV) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# Wording from a datasheet or the order email. Each tuple maps to a known catalog row.
_DATASHEET = (
    (("77 ghz", "gaas power", "mmwave power"), "PA-77G-HE"),
    (("10 gsps", "10gsps", "high-speed adc"), "ADC-12G-HE"),
    (("radiation-hardened fpga", "rad-hard fpga", "radiation hardened fpga"), "FPGA-RH-X"),
    (("sub-6 ghz transceiver", "sub-6ghz transceiver"), "RF-TRX-IN"),
)


def _from_datasheet(description: str) -> str | None:
    text = description.lower()
    for phrases, part in _DATASHEET:
        if any(p in text for p in phrases):
            return part
    return None


def classify(part_number: str, ledger: Ledger, description: str = "") -> Classification:
    pn = part_number.strip().upper()
    row = load_catalog().get(pn)
    if row is None:
        family = _from_datasheet(description)
        row = load_catalog().get(family) if family else None
        if row is None:
            eid = ledger.add(f"Part {part_number} is not in the catalog", None, "catalog:miss")
            return Classification(part_number=part_number, found=False, evidence_ids=[eid])
        value = {k: row[k] for k in ("description", "controlled", "scomet_category", "eccn", "us_origin", "part_class", "needs")}
        eid = ledger.add(f"Datasheet wording for {part_number} matched {family}", value, f"datasheet:{family}")
        return Classification(
            part_number=pn, found=True, controlled=_bool(row["controlled"]),
            scomet_category=row["scomet_category"] or None, eccn=row["eccn"] or None, us_origin=_bool(row["us_origin"]),
            part_class=row["part_class"], needs=[n for n in row["needs"].split(";") if n],
            max_units_per_engineer=int(row["max_units_per_engineer"]),
            max_units_distributor_small=int(row["max_units_distributor_small"]), evidence_ids=[eid])
    idx = list(load_catalog()).index(pn) + 2  # CSV line number (header is line 1)
    value = {k: row[k] for k in ("description", "controlled", "scomet_category", "eccn", "us_origin", "part_class", "needs")}
    eid = ledger.add(f"Catalog entry for {pn}", value, f"catalog:row/{idx}")
    return Classification(
        part_number=pn, found=True, controlled=_bool(row["controlled"]),
        scomet_category=row["scomet_category"] or None, eccn=row["eccn"] or None, us_origin=_bool(row["us_origin"]),
        part_class=row["part_class"], needs=[n for n in row["needs"].split(";") if n],
        max_units_per_engineer=int(row["max_units_per_engineer"]),
        max_units_distributor_small=int(row["max_units_distributor_small"]), evidence_ids=[eid])


def _best(regime: str, key: str, dest: str) -> tuple[int, dict] | None:
    best = None
    for i, r in enumerate(load_rules()):
        if r["regime"] != regime:
            continue
        m, d = r["match"], r["destination"]
        if not (m == "*" or key.startswith(m)) or d not in ("*", dest):
            continue
        score = (d == dest, len(m) if m != "*" else 0)
        if best is None or score > best[0]:
            best = (score, i, r)
    return (best[1], best[2]) if best else None


def licence(cls: Classification, dest_country: str, ledger: Ledger) -> LicenceResult:
    dest = (dest_country or "").upper()
    required, reasons, docs, ids = False, [], [], []
    checks = []
    if cls.controlled:
        checks.append(("SCOMET", cls.scomet_category or "*"))
    if cls.us_origin and cls.eccn:
        checks.append(("EAR", cls.eccn))
    for regime, key in checks:
        hit = _best(regime, key, dest)
        if hit is None:
            continue
        i, r = hit
        req = _bool(r["required"])
        required |= req
        reasons.append(f"{regime}: {r['reason']}")
        docs += [d for d in r["documents"].split(";") if d]
        ids.append(ledger.add(f"{regime} licence rule for {cls.part_number} to {dest}", {"required": req, "reason": r["reason"]},
                              f"licence_rules:row/{i + 2}"))
    if not checks:
        reasons.append("Not SCOMET-controlled and not US-origin: no licence needed")
        ids.append(ledger.add(f"No licence regime applies to {cls.part_number}", False, "licence_rules:none"))
    return LicenceResult(part_number=cls.part_number, required=required, reason="; ".join(reasons),
                         documents=list(dict.fromkeys(docs)), evidence_ids=ids)
