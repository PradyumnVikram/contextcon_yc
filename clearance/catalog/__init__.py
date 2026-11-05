"""Part classification and licence rules. OWNER: Person A (tasks A4).

STUB (S5): hard-coded parts so the pipeline runs end to end. Replace with a
reader for data/catalog.csv and data/licence_rules.csv. Keep the signatures.
"""
from __future__ import annotations

from clearance.evidence import Ledger
from clearance.models import Classification, LicenceResult

STUB = True

_FAKE_CATALOG = {
    "PA-77G-HE": dict(controlled=True, scomet_category="8A?", eccn="3A001.b.2", us_origin=True,
                      part_class="high_end", needs=["rf", "antenna", "radar"],
                      max_units_per_engineer=5, max_units_distributor_small=20),
    "FPGA-C10": dict(controlled=False, scomet_category=None, eccn="EAR99", us_origin=True,
                     part_class="commodity", needs=["fpga"],
                     max_units_per_engineer=50, max_units_distributor_small=500),
    "ADC-12G-HE": dict(controlled=True, scomet_category="8A?", eccn="3A001.a.5", us_origin=True,
                       part_class="high_end", needs=["mixed_signal", "test_lab"],
                       max_units_per_engineer=5, max_units_distributor_small=20),
}


def classify(part_number: str, ledger: Ledger) -> Classification:
    row = _FAKE_CATALOG.get(part_number)
    if row is None:
        eid = ledger.add(f"Part {part_number} is not in the catalog", None, "catalog:miss")
        return Classification(part_number=part_number, found=False, evidence_ids=[eid])
    eid = ledger.add(f"Part {part_number} catalog entry", row, f"catalog:stub/{part_number}")
    return Classification(part_number=part_number, found=True, evidence_ids=[eid], **row)


def licence(cls: Classification, dest_country: str, ledger: Ledger) -> LicenceResult:
    required = bool(cls.found and cls.controlled and dest_country != "IN")
    reason = "Controlled part exported outside India" if required else "No licence needed (stub rule)"
    eid = ledger.add(f"Licence for {cls.part_number} to {dest_country}: {reason}", required, "licence_rules:stub")
    docs = ["SCOMET application", "End-user certificate"] if required else []
    return LicenceResult(part_number=cls.part_number, required=required, reason=reason, documents=docs, evidence_ids=[eid])
