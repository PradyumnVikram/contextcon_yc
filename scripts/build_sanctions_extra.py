"""Build data/sanctions_extra.csv from the UN, EU, and UK sanctions lists.

Keeps entities only (no individuals). Output columns match data/csl.csv so screening
loads the file with no other changes.

    python scripts/build_sanctions_extra.py /tmp/sanctions/un.xml /tmp/sanctions/eu.csv /tmp/sanctions/uk.csv

Sources:
  UN  https://scsanctions.un.org/resources/xml/en/consolidated.xml
  EU  https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content?token=dG9rZW4tMjAxNw
  UK  https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv
"""
from __future__ import annotations

import csv
import itertools
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

csv.field_size_limit(10_000_000)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sanctions_extra.csv"
COLUMNS = ["id", "source", "name", "alt_names", "addresses", "countries"]

# EU files use alpha-3. Orders in this app use alpha-2.
ISO3 = {
    "AFG": "AF", "ALB": "AL", "DZA": "DZ", "ARE": "AE", "ARG": "AR", "ARM": "AM", "AUS": "AU",
    "AUT": "AT", "AZE": "AZ", "BHR": "BH", "BGD": "BD", "BLR": "BY", "BEL": "BE", "BIH": "BA",
    "BRA": "BR", "BGR": "BG", "BFA": "BF", "BDI": "BI", "KHM": "KH", "CMR": "CM", "CAN": "CA",
    "CAF": "CF", "TCD": "TD", "CHL": "CL", "CHN": "CN", "COL": "CO", "COM": "KM", "COD": "CD",
    "COG": "CG", "CRI": "CR", "CIV": "CI", "HRV": "HR", "CUB": "CU", "CYP": "CY", "CZE": "CZ",
    "DNK": "DK", "DJI": "DJ", "EGY": "EG", "ERI": "ER", "EST": "EE", "ETH": "ET", "FIN": "FI",
    "FRA": "FR", "GEO": "GE", "DEU": "DE", "GHA": "GH", "GRC": "GR", "GTM": "GT", "GIN": "GN",
    "HND": "HN", "HKG": "HK", "HUN": "HU", "IND": "IN", "IDN": "ID", "IRN": "IR", "IRQ": "IQ",
    "IRL": "IE", "ISR": "IL", "ITA": "IT", "JPN": "JP", "JOR": "JO", "KAZ": "KZ", "KEN": "KE",
    "PRK": "KP", "KOR": "KR", "KWT": "KW", "KGZ": "KG", "LBN": "LB", "LBY": "LY", "LIE": "LI",
    "LTU": "LT", "LUX": "LU", "MYS": "MY", "MLI": "ML", "MLT": "MT", "MEX": "MX", "MDA": "MD",
    "MNG": "MN", "MNE": "ME", "MAR": "MA", "MOZ": "MZ", "MMR": "MM", "NLD": "NL", "NZL": "NZ",
    "NIC": "NI", "NER": "NE", "NGA": "NG", "NOR": "NO", "OMN": "OM", "PAK": "PK", "PSE": "PS",
    "PAN": "PA", "PRY": "PY", "PER": "PE", "PHL": "PH", "POL": "PL", "PRT": "PT", "QAT": "QA",
    "ROU": "RO", "RUS": "RU", "SAU": "SA", "SEN": "SN", "SRB": "RS", "SGP": "SG", "SVK": "SK",
    "SVN": "SI", "SOM": "SO", "ZAF": "ZA", "SSD": "SS", "ESP": "ES", "LKA": "LK", "SDN": "SD",
    "SWE": "SE", "CHE": "CH", "SYR": "SY", "TWN": "TW", "TJK": "TJ", "TZA": "TZ", "THA": "TH",
    "TUN": "TN", "TUR": "TR", "TKM": "TM", "UGA": "UG", "UKR": "UA", "GBR": "GB", "USA": "US",
    "UZB": "UZ", "VEN": "VE", "VNM": "VN", "YEM": "YE", "ZWE": "ZW", "ZMB": "ZM",
}

NAMES = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "argentina": "AR", "armenia": "AM",
    "australia": "AU", "austria": "AT", "azerbaijan": "AZ", "bahrain": "BH", "bangladesh": "BD",
    "belarus": "BY", "belgium": "BE", "bosnia and herzegovina": "BA", "brazil": "BR",
    "bulgaria": "BG", "cambodia": "KH", "cameroon": "CM", "canada": "CA",
    "central african republic": "CF", "chad": "TD", "chile": "CL", "china": "CN",
    "colombia": "CO", "congo": "CG", "congo (democratic republic)": "CD",
    "democratic republic of the congo": "CD", "cuba": "CU", "cyprus": "CY",
    "czech republic": "CZ", "czechia": "CZ", "denmark": "DK", "egypt": "EG", "eritrea": "ER",
    "estonia": "EE", "ethiopia": "ET", "finland": "FI", "france": "FR", "georgia": "GE",
    "germany": "DE", "ghana": "GH", "greece": "GR", "hong kong": "HK", "hungary": "HU",
    "india": "IN", "indonesia": "ID", "iran": "IR", "iran (islamic republic of)": "IR",
    "iraq": "IQ", "ireland": "IE", "israel": "IL", "italy": "IT", "japan": "JP", "jordan": "JO",
    "kazakhstan": "KZ", "kenya": "KE", "north korea": "KP",
    "korea, democratic people's republic of": "KP", "democratic people's republic of korea": "KP",
    "south korea": "KR", "kuwait": "KW", "kyrgyzstan": "KG", "lebanon": "LB", "libya": "LY",
    "libyan arab jamahiriya": "LY", "lithuania": "LT", "luxembourg": "LU", "malaysia": "MY",
    "mali": "ML", "mexico": "MX", "moldova": "MD", "republic of moldova": "MD",
    "myanmar": "MM", "netherlands": "NL", "nicaragua": "NI", "nigeria": "NG", "norway": "NO",
    "oman": "OM", "pakistan": "PK", "occupied palestinian territories": "PS",
    "state of palestine": "PS", "philippines": "PH", "poland": "PL", "portugal": "PT",
    "qatar": "QA", "romania": "RO", "russia": "RU", "russian federation": "RU",
    "saudi arabia": "SA", "serbia": "RS", "singapore": "SG", "somalia": "SO",
    "south africa": "ZA", "south sudan": "SS", "spain": "ES", "sri lanka": "LK", "sudan": "SD",
    "sweden": "SE", "switzerland": "CH", "syria": "SY", "syrian arab republic": "SY",
    "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH", "tunisia": "TN", "turkey": "TR",
    "türkiye": "TR", "turkiye": "TR", "turkmenistan": "TM", "uganda": "UG", "ukraine": "UA",
    "united arab emirates": "AE", "united kingdom": "GB", "united states": "US",
    "united states of america": "US", "uzbekistan": "UZ", "venezuela": "VE",
    "viet nam": "VN", "vietnam": "VN", "yemen": "YE", "zimbabwe": "ZW",
}


def to_iso2(value: str) -> str | None:
    v = (value or "").strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    if len(v) == 3 and v.isalpha() and v.upper() in ISO3:
        return ISO3[v.upper()]
    return NAMES.get(v.lower())


def _join(parts: list[str]) -> str:
    return ";".join(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


def from_un(path: Path) -> list[dict]:
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "ENTITY":
            continue
        name = (el.findtext("FIRST_NAME") or "").strip()
        aliases = [a.text.strip() for a in el.iter("ALIAS_NAME") if a.text and a.text.strip() and a.text.strip() != name]
        countries, addresses = [], []
        for addr in el.findall("ENTITY_ADDRESS"):
            country = (addr.findtext("COUNTRY") or "").strip()
            city = (addr.findtext("CITY") or "").strip()
            street = (addr.findtext("STREET") or "").strip()
            bits = [b for b in (street, city, country) if b]
            if bits:
                addresses.append(", ".join(bits))
            iso = to_iso2(country)
            if iso:
                countries.append(iso)
        ref = (el.findtext("REFERENCE_NUMBER") or el.findtext("DATAID") or "").strip()
        if name:
            out.append({
                "id": f"UN-{ref or len(out)}",
                "source": "UN Security Council Consolidated List",
                "name": name,
                "alt_names": _join(aliases),
                "addresses": _join(addresses),
                "countries": _join(countries),
            })
        el.clear()
    return out


def from_eu(path: Path) -> list[dict]:
    groups: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        header = next(csv.reader(f, delimiter=";"))
        idx = {name: header.index(name) for name in
               ("Entity_logical_id", "Subject_type", "Naal_wholename", "Addr_country", "EU_ref_num")}
        need = max(idx.values())
        for row in csv.reader(f, delimiter=";"):
            if len(row) <= need or row[idx["Subject_type"]] != "E":
                continue
            eid = row[idx["Entity_logical_id"]] or row[idx["EU_ref_num"]]
            if not eid:
                continue
            g = groups.setdefault(eid, {"names": [], "countries": [], "ref": row[idx["EU_ref_num"]]})
            name = row[idx["Naal_wholename"]].strip()
            if name and name not in g["names"]:
                g["names"].append(name)
            iso = to_iso2(row[idx["Addr_country"]])
            if iso and iso not in g["countries"]:
                g["countries"].append(iso)
    out = []
    for eid, g in groups.items():
        if not g["names"]:
            continue
        out.append({
            "id": f"EU-{g['ref'] or eid}",
            "source": "EU Financial Sanctions",
            "name": g["names"][0],
            "alt_names": _join(g["names"][1:]),
            "addresses": "",
            "countries": _join(g["countries"]),
        })
    return out


def from_uk(path: Path) -> list[dict]:
    groups: dict[str, dict] = {}
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        header = None
        for line in f:
            if line.startswith("Last Updated,"):
                header = line
                break
        if header is None:
            raise SystemExit(f"{path} has no UK sanctions header")
        reader = csv.DictReader(itertools.chain([header], f))
        for row in reader:
            if (row.get("Designation Type") or "").strip() != "Entity":
                continue
            uid = (row.get("Unique ID") or "").strip()
            if not uid:
                continue
            parts = [(row.get(f"Name {i}") or "").strip() for i in range(1, 7)]
            name = (row.get("Name 6") or "").strip() or " ".join(p for p in parts if p)
            if not name:
                continue
            g = groups.setdefault(uid, {"names": [], "countries": []})
            if name not in g["names"]:
                g["names"].append(name)
            iso = to_iso2(row.get("Address Country") or "")
            if iso and iso not in g["countries"]:
                g["countries"].append(iso)
    return [{
        "id": f"UK-{uid}",
        "source": "UK Sanctions List",
        "name": g["names"][0],
        "alt_names": _join(g["names"][1:]),
        "addresses": "",
        "countries": _join(g["countries"]),
    } for uid, g in groups.items()]


def main(un: Path, eu: Path, uk: Path) -> None:
    rows = from_un(un) + from_eu(eu) + from_uk(uk)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} entities to {OUT}")
    from collections import Counter
    for source, n in Counter(r["source"] for r in rows).items():
        print(f"{n:6d}  {source}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: python scripts/build_sanctions_extra.py un.xml eu.csv uk.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
