"""US Consolidated Screening List: download, convert, load (task A5).

    python -m clearance.screening.csl            # download from trade.gov and write data/csl.csv
    python -m clearance.screening.csl raw.csv    # convert an already-downloaded consolidated.csv

data/csl.csv (git-ignored) keeps the US consolidated list.
data/sanctions_extra.csv (git-ignored) keeps UN, EU, and UK entities, built by
scripts/build_sanctions_extra.py. data/csl_demo.csv holds synthetic demo names.
All three are loaded together.
"""
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from clearance import config

CSL_URL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv"
CSL_CSV = config.DATA_DIR / "csl.csv"
CSL_DEMO_CSV = config.DATA_DIR / "csl_demo.csv"
# UN, EU, and UK entity lists, same columns as csl.csv. Built by scripts/build_sanctions_extra.py.
EXTRA_CSV = config.DATA_DIR / "sanctions_extra.csv"
COLUMNS = ["id", "source", "name", "alt_names", "addresses", "countries"]

csv.field_size_limit(10_000_000)


@dataclass
class Entry:
    id: str
    source: str
    name: str
    alt_names: list[str]
    addresses: list[str]
    countries: set[str] = field(default_factory=set)


def _countries(addresses: str) -> list[str]:
    out = []
    for a in addresses.split(";"):
        tail = a.strip().split(",")[-1].strip()
        if re.fullmatch(r"[A-Z]{2}", tail):
            out.append(tail)
    return sorted(set(out))


def convert(raw_path: Path, out_path: Path = CSL_CSV) -> int:
    """Keep non-individual entries (entities, vessels, aircraft) with the columns screening needs."""
    n = 0
    with open(raw_path, newline="", encoding="utf-8") as fin, open(out_path, "w", newline="", encoding="utf-8") as fout:
        w = csv.DictWriter(fout, fieldnames=COLUMNS)
        w.writeheader()
        for r in csv.DictReader(fin):
            if (r.get("type") or "").strip().lower() == "individual":
                continue
            w.writerow({"id": r["_id"], "source": r["source"], "name": r["name"], "alt_names": r.get("alt_names", ""),
                        "addresses": r.get("addresses", ""), "countries": ";".join(_countries(r.get("addresses", "")))})
            n += 1
    return n


def download(out_path: Path = CSL_CSV) -> int:
    import tempfile

    import httpx
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        with httpx.stream("GET", CSL_URL, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                tmp.write(chunk)
    return convert(Path(tmp.name), out_path)


def _read(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [Entry(id=r["id"], source=r["source"], name=r["name"],
                      alt_names=[a.strip() for a in r["alt_names"].split(";") if a.strip()],
                      addresses=[a.strip() for a in r["addresses"].split(";") if a.strip()],
                      countries={c for c in r["countries"].split(";") if c})
                for r in csv.DictReader(f)]


@lru_cache(maxsize=4)
def load(paths: tuple[Path, ...] | None = None) -> list[Entry]:
    """US CSL (if downloaded) + UN/EU/UK entities (if built) + the synthetic demo list.

    Module globals are read at call time so tests can point CSL_CSV and EXTRA_CSV at fixtures.
    """
    return [e for p in (paths or (CSL_CSV, EXTRA_CSV, CSL_DEMO_CSV)) for e in _read(p)]


if __name__ == "__main__":
    n = convert(Path(sys.argv[1])) if len(sys.argv) > 1 else download()
    print(f"wrote {n} entries to {CSL_CSV}")
