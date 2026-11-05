"""Generate data/demo_crustdata/*.json: SYNTHETIC companies in Crustdata response shapes (task A10).

The demo must never present a real, unlisted company as suspicious, so every demo buyer is synthetic and
served from these fixtures. Shapes follow docs.crustdata.com (2025-11-01): company_data sections
basic_info / headcount / taxonomy / locations / web_traffic, person profiles from /person/search.

    python scripts/make_demo_crustdata.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "demo_crustdata"
rng = random.Random(42)


def company(cid, name, domain, country, industry, description, founded, total, roles, yoy, visitors):
    return {
        "crustdata_company_id": cid,
        "basic_info": {"name": name, "primary_domain": domain, "website": f"https://{domain}",
                       "description": description, "year_founded": founded},
        "headcount": {"total": total, "by_role_absolute": roles,
                      "growth_percent": {"yoy": yoy}},
        "taxonomy": {"professional_network_industry": industry},
        "locations": {"country": country},
        "web_traffic": {"domain_traffic": [{"domain": domain, "monthly_visitors": visitors}]},
    }


def person(pid, name, title, function, seniority, skills, past):
    return {"crustdata_person_id": pid,
            "basic_profile": {"name": name, "current_title": title},
            "experience": {"employment_details": {
                "current": {"title": title, "function_category": function, "seniority_level": seniority},
                "past": [{"name": p, "title": "Engineer" if function == "Engineering" else "Executive"} for p in past]}},
            "skills": {"professional_network_skills": skills}}


COMPANIES = {
    "synthetic-radar.example": company(
        9001, "Synthetic Radar Systems", "synthetic-radar.example", "India", "Defense and Space Manufacturing",
        "Designs and manufactures automotive and defence radar modules, mmWave front-ends and antenna arrays.",
        2009, 180, {"Engineering": 95, "Research": 20, "Sales": 20, "Operations": 30, "Finance": 15}, 8.0, 42000),
    "synthetic-components.example": company(
        9002, "Synthetic Components distributor", "synthetic-components.example", "India", "Wholesale",
        "Authorised distributor of electronic components for Indian OEMs.",
        2004, 120, {"Sales": 55, "Operations": 45, "Engineering": 6, "Finance": 14}, 3.0, 95000),
    "synthetic-telecomlabs.example": company(
        9003, "Synthetic Telecom Labs", "synthetic-telecomlabs.example", "India", "Telecommunications",
        "Telecom equipment design lab: 5G radio units, FPGA prototyping and RF test.",
        2012, 300, {"Engineering": 170, "Research": 40, "Sales": 30, "Operations": 40, "Finance": 20}, 12.0, 60000),
    "synthetic-hardware.example": company(
        9004, "Synthetic Hardware Works", "synthetic-hardware.example", "India", "Computer Hardware Manufacturing",
        "Design and manufacture of embedded control boards for industrial automation.",
        2016, 12, {"Engineering": 3, "Operations": 5, "Sales": 3, "Finance": 1}, 0.0, 14000),
    "synthetic-shell.example": company(
        9005, "Synthetic shell Traders", "synthetic-shell.example", "India", "Wholesale",
        "General trading, import and export of goods.",
        2025, 5, {"Sales": 3, "Operations": 2}, 0.0, 250),
}

ENGINEER_SKILLS = {
    "synthetic-radar.example": [["RF Design", "Radar", "mmWave", "Antenna Design"], ["Microwave Engineering", "HFSS", "Radar Signal Processing"],
                                ["RF Power Amplifiers", "GaAs", "Antenna Arrays"]],
    "synthetic-telecomlabs.example": [["FPGA", "Verilog", "5G NR"], ["RF Engineering", "LTE", "Antenna Design"], ["Xilinx", "VHDL", "Telecom"]],
    "synthetic-hardware.example": [["FPGA", "Verilog", "Embedded Systems"], ["PCB Design", "FPGA", "VHDL"], ["Embedded C", "FPGA"]],
}
FIRST = ["Aarav", "Diya", "Rohan", "Isha", "Kabir", "Meera", "Arjun", "Ananya", "Vikram", "Priya", "Nikhil", "Sneha"]
LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Nair", "Gupta", "Menon", "Rao", "Das", "Kulkarni"]


def people_for(domain, n_eng, n_sales, n_ops, eng_past, other_past):
    out, pid = [], int(COMPANIES[domain]["crustdata_company_id"]) * 100
    skills = ENGINEER_SKILLS.get(domain, [["Sales"]])
    for i in range(n_eng):
        pid += 1
        out.append(person(pid, f"{rng.choice(FIRST)} {rng.choice(LAST)}", rng.choice(["RF Engineer", "Senior Hardware Engineer", "FPGA Engineer", "Design Engineer"]),
                          "Engineering", "Senior" if i % 3 else "Director", skills[i % len(skills)], eng_past))
    for i in range(n_sales):
        pid += 1
        out.append(person(pid, f"{rng.choice(FIRST)} {rng.choice(LAST)}", rng.choice(["Sales Manager", "Business Development Executive", "Procurement Lead"]),
                          "Sales", "Experienced Manager", ["Sales", "Negotiation"], other_past))
    for i in range(n_ops):
        pid += 1
        out.append(person(pid, f"{rng.choice(FIRST)} {rng.choice(LAST)}", rng.choice(["Logistics Coordinator", "Operations Manager", "Import Export Executive"]),
                          "Operations", "Entry Level", ["Logistics", "Customs Clearance"], other_past))
    return out


PEOPLE = {
    "synthetic-radar.example": people_for("synthetic-radar.example", 16, 4, 5, ["Demo Defence Electronics", "Demo Telecom Equipment"], ["Demo Electronics Pvt Ltd"]),
    "synthetic-components.example": people_for("synthetic-components.example", 1, 12, 10, ["Demo Electronics Pvt Ltd"], ["Demo Trading Co", "Demo Electronics Distribution"]),
    "synthetic-telecomlabs.example": people_for("synthetic-telecomlabs.example", 15, 4, 4, ["Demo Telecom Equipment", "Demo Semiconductor"], ["Demo Telecom Equipment"]),
    "synthetic-hardware.example": people_for("synthetic-hardware.example", 3, 2, 3, ["Demo Industrial Electronics"], ["Demo Electronics Pvt Ltd"]),
    "synthetic-shell.example": people_for("synthetic-shell.example", 0, 2, 2, [], ["Demo General Trading", "Demo Import Export"]),
}


def peers(industry, n, hc, eng, visitors):
    out = []
    for i in range(n):
        total = rng.randint(*hc)
        e = rng.uniform(*eng)
        out.append({"crustdata_company_id": 80000 + len(industry) * 100 + i,
                    "basic_info": {"name": f"Peer {industry[:12]} {i + 1}", "primary_domain": f"peer{i + 1}.{industry[:4].lower()}.example",
                                   "year_founded": rng.randint(1995, 2020)},
                    "headcount": {"total": total, "by_role_percent": {"Engineering": round(100 * e, 1)}},
                    "web_traffic": {"domain_traffic": [{"monthly_visitors": rng.randint(*visitors)}]}})
    return out


PEERS = {
    "Defense and Space Manufacturing": peers("Defense and Space Manufacturing", 30, (60, 800), (0.25, 0.65), (5000, 120000)),
    "Telecommunications": peers("Telecommunications", 30, (80, 1500), (0.25, 0.6), (8000, 200000)),
    "Computer Hardware Manufacturing": peers("Computer Hardware Manufacturing", 30, (8, 150), (0.15, 0.55), (1500, 50000)),
    "Wholesale": peers("Wholesale", 30, (25, 600), (0.0, 0.1), (4000, 250000)),
}

# --- Diversion ring (all synthetic): three ordinary-looking small firms sharing one director. -----------------
# Each looks routine on its own; together they order most of a radar seeker front-end.
RING = {
    "orbit-electronics.example": ("Synthetic Orbit Electronics", "Repair and calibration of electronic test equipment.", 2015, 42,
                                  {"Engineering": 14, "Operations": 14, "Sales": 10, "Finance": 4}, 9000),
    "nimbus-instruments.example": ("Synthetic Nimbus Instruments", "Servicing and spares for laboratory instruments.", 2013, 55,
                                   {"Engineering": 18, "Operations": 18, "Sales": 14, "Finance": 5}, 12000),
    "delta-systems.example": ("Synthetic Delta Systems", "Embedded electronics design services for industrial clients.", 2016, 38,
                              {"Engineering": 14, "Operations": 12, "Sales": 9, "Finance": 3}, 7000),
}
SHARED_DIRECTOR = person(777001, "Rakesh Varma", "Director", "Operations", "Owner / Partner", ["Business Strategy"],
                         ["Gulf Swift Cargo FZE", "Demo General Trading"])
for i, (dom, (name, desc, founded, total, roles, visitors)) in enumerate(RING.items()):
    COMPANIES[dom] = company(9100 + i, name, dom, "India", "Computer Hardware Manufacturing", desc, founded, total,
                             roles, 4.0, visitors)
    ENGINEER_SKILLS[dom] = [["Embedded C", "PCB Design"], ["Test Equipment", "Calibration"], ["Firmware", "Electronics"]]
    PEOPLE[dom] = [SHARED_DIRECTOR] + people_for(dom, 4, 2, 2, ["Demo Electronics Pvt Ltd"], ["Demo Trading Co"])

# --- A firm whose managing director came from a listed entity (synthetic name on data/csl_demo.csv). -------------
COMPANIES["apex-components.example"] = company(
    9200, "Synthetic Apex Components", "apex-components.example", "India", "Computer Hardware Manufacturing",
    "Design of power electronics for industrial drives.", 2012, 60,
    {"Engineering": 26, "Operations": 18, "Sales": 12, "Finance": 4}, 2.0, 15000)
ENGINEER_SKILLS["apex-components.example"] = [["Power Electronics", "PCB Design"], ["Embedded C", "Motor Control"]]
PEOPLE["apex-components.example"] = [person(777101, "Imran Qureshi", "Managing Director", "Operations", "CXO",
                                            ["Business Development"], ["Prohibited Microwave Systems Private Limited",
                                                                       "Demo Electronics Pvt Ltd"])] + \
    people_for("apex-components.example", 6, 2, 2, ["Demo Industrial Electronics"], ["Demo Electronics Pvt Ltd"])

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [("companies.json", COMPANIES), ("people.json", PEOPLE), ("peers.json", PEERS)]:
        (OUT / name).write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {len(COMPANIES)} companies, {sum(map(len, PEOPLE.values()))} people, "
          f"{sum(map(len, PEERS.values()))} peers to {OUT}")
