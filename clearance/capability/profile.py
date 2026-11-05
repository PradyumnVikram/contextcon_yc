"""Crustdata JSON -> plain profiles (task A6). The ONLY place that knows Crustdata field names, so a field
rename found in A2 is a one-line fix here. Parsing is defensive: missing sections become None, never errors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ENGINEERING_FUNCS = ("engineering", "research", "information technology", "product")
SALES_FUNCS = ("sales", "marketing", "business development", "purchasing", "procurement")
OPS_FUNCS = ("operations", "logistics", "support", "customer success", "administrative")


def _get(d: Any, path: str) -> Any:
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _find_number(obj: Any, key: str) -> float | None:
    """First numeric value of `key` anywhere in a nested dict/list (web_traffic shape is not fully documented)."""
    if isinstance(obj, dict):
        if isinstance(obj.get(key), (int, float)):
            return float(obj[key])
        for v in obj.values():
            if (n := _find_number(v, key)) is not None:
                return n
    elif isinstance(obj, list):
        vals = [n for v in obj if (n := _find_number(v, key)) is not None]
        return max(vals) if vals else None
    return None


def func_bucket(name: str) -> str:
    n = (name or "").lower()
    if any(f in n for f in ENGINEERING_FUNCS):
        return "engineering"
    if any(f in n for f in SALES_FUNCS):
        return "sales"
    if any(f in n for f in OPS_FUNCS):
        return "operations"
    return "other"


@dataclass
class CompanyProfile:
    raw: dict
    name: str | None
    domain: str | None
    description: str | None
    industry: str | None
    country: str | None
    year_founded: int | None
    headcount: int | None
    by_role: dict[str, float]          # function -> headcount (absolute) or percent, see by_role_is_pct
    growth_yoy_pct: float | None
    monthly_visitors: float | None
    by_role_is_pct: bool = False

    @property
    def engineering_share(self) -> float | None:
        eng = sum(v for k, v in self.by_role.items() if func_bucket(k) == "engineering")
        if self.by_role_is_pct:  # by_role_percent may list only some functions; read it as a percentage
            return eng / 100 if self.by_role else None
        total = sum(self.by_role.values())
        return eng / total if total else None


def parse_company(cd: dict) -> CompanyProfile:
    by_role_abs = _get(cd, "headcount.by_role_absolute") or {}
    by_role_pct = _get(cd, "headcount.by_role_percent") or {}
    by_role = {k: float(v) for k, v in (by_role_abs or by_role_pct).items() if isinstance(v, (int, float))}
    industry = _get(cd, "taxonomy.professional_network_industry")
    if isinstance(industry, list):
        industry = industry[0] if industry else None
    year = _get(cd, "basic_info.year_founded")
    return CompanyProfile(
        raw=cd, name=_get(cd, "basic_info.name"), domain=_get(cd, "basic_info.primary_domain"),
        description=_get(cd, "basic_info.description"), industry=industry, country=_get(cd, "locations.country"),
        year_founded=int(year) if isinstance(year, (int, float)) or (isinstance(year, str) and year.isdigit()) else None,
        headcount=_get(cd, "headcount.total"), by_role=by_role,
        growth_yoy_pct=_get(cd, "headcount.growth_percent.yoy"),
        monthly_visitors=_find_number(cd.get("web_traffic"), "monthly_visitors"),
        by_role_is_pct=not by_role_abs and bool(by_role_pct),
    )


@dataclass
class PersonProfile:
    person_id: str
    name: str
    title: str
    function: str
    seniority: str
    skills: list[str] = field(default_factory=list)
    past_employers: list[str] = field(default_factory=list)


def parse_person(p: dict) -> PersonProfile:
    cur = _get(p, "experience.employment_details.current") or {}
    if isinstance(cur, list):
        cur = cur[0] if cur else {}
    past = _get(p, "experience.employment_details.past") or []
    skills = _get(p, "skills.professional_network_skills") or []
    return PersonProfile(
        person_id=str(p.get("crustdata_person_id", "")),
        name=_get(p, "basic_profile.name") or "",
        title=_get(p, "basic_profile.current_title") or cur.get("title") or "",
        function=cur.get("function_category") or "",
        seniority=cur.get("seniority_level") or "",
        skills=[s for s in skills if isinstance(s, str)],
        past_employers=[e.get("name", "") for e in past if isinstance(e, dict) and e.get("name")],
    )
