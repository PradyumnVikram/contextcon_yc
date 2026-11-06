"""Restricted-party screening against the US CSL (task A5). OWNER: Person A.

normalize -> block (same country, or shared first token) -> score -> threshold (AGENTS §4.2):
    score = 0.60*token + 0.25*jaro_winkler + 0.15*address   (address weight re-spread when unknown)
    token = mean(token_set_ratio, token_sort_ratio), so a one-word listed name can't match every longer name
    exact_hit: normalised names identical (or score >= 97) AND country matches
    fuzzy_hit: score >= 85
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from functools import lru_cache

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from clearance import config, store
from clearance.evidence import Ledger
from clearance.models import Match, Party, ScreeningResult
from clearance.screening import csl

_SUFFIX_RE = re.compile(r"\b(" + "|".join(sorted({
    "pvt", "private", "ltd", "limited", "llc", "l l c", "inc", "incorporated", "co", "company", "corp", "corporation",
    "plc", "gmbh", "fze", "fzco", "fzc", "fz llc", "jsc", "ojsc", "pjsc", "ooo", "sa", "srl", "bv", "pte", "sdn bhd",
}, key=len, reverse=True)) + r")\b")
_TRANSLIT = [("ph", "f"), ("kh", "k"), ("ck", "k"), ("ee", "i"), ("oo", "u"), ("y", "i")]


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.replace("&", " and "))
    s = _SUFFIX_RE.sub(" ", s)
    return " ".join(s.split())


def _translit(s: str) -> str:
    for a, b in _TRANSLIT:
        s = s.replace(a, b)
    return s


@lru_cache(maxsize=2)
def _index():
    """Normalised names per entry, plus blocking indexes by country and by first token."""
    entries = csl.load()
    names: list[tuple[int, str, str]] = []  # (entry idx, raw name, normalised name)
    by_country: dict[str, set[int]] = defaultdict(set)
    by_token: dict[str, set[int]] = defaultdict(set)
    for i, e in enumerate(entries):
        for raw in [e.name, *e.alt_names]:
            n = normalize(raw)
            if not n:
                continue
            names.append((i, raw, n))
            by_token[_translit(n.split()[0])].add(i)
        for c in e.countries:
            by_country[c].add(i)
    return entries, names, by_country, by_token


def _score(q: str, cand: str, q_addr: str | None, cand_addrs: list[str]) -> tuple[float, dict[str, float]]:
    qt, ct = _translit(q), _translit(cand)
    # token_set alone scores 100 whenever one name's words are a subset of the other's ("astra" vs
    # "astra microwave products"); averaging with token_sort keeps typo tolerance but penalises extra words.
    ts = (float(fuzz.token_set_ratio(qt, ct)) + float(fuzz.token_sort_ratio(qt, ct))) / 2
    jw = 100.0 * JaroWinkler.normalized_similarity(qt, ct)
    w = config.SCREEN_WEIGHTS
    if q_addr and cand_addrs:
        ad = max(float(fuzz.token_set_ratio(q_addr.lower(), a.lower())) for a in cand_addrs)
        score = w["token_set"] * ts + w["jaro_winkler"] * jw + w["address"] * ad
        br = {"token_set": round(ts, 1), "jaro_winkler": round(jw, 1), "address": round(ad, 1)}
    else:
        score = (w["token_set"] * ts + w["jaro_winkler"] * jw) / (w["token_set"] + w["jaro_winkler"])
        br = {"token_set": round(ts, 1), "jaro_winkler": round(jw, 1)}  # no address to compare
    return round(score, 1), br


def screen(party: Party, ledger: Ledger) -> ScreeningResult:
    entries, names, by_country, by_token = _index()
    q = normalize(party.name)
    is_forwarder = any(k in party.name.lower() for k in config.FORWARDER_KEYWORDS)
    candidates = set(by_token.get(_translit(q.split()[0]), set())) if q else set()
    if party.country:
        candidates |= by_country.get(party.country.upper(), set())

    best: dict[int, Match] = {}
    for i, raw, n in names:
        if i not in candidates:
            continue
        score, br = _score(q, n, party.address, entries[i].addresses)
        e = entries[i]
        same_country = bool(party.country) and party.country.upper() in e.countries
        exact = (n == q or score >= config.SCREEN_EXACT_SCORE) and same_country
        if score >= config.SCREEN_FUZZY_SCORE or exact:
            m = Match(csl_entry_id=e.id, listed_name=raw, score=100.0 if n == q else score, breakdown=br,
                      listed_record={"source": e.source, "name": e.name, "alt_names": e.alt_names[:5],
                                     "addresses": e.addresses[:3], "countries": sorted(e.countries),
                                     "exact": exact})
            if i not in best or m.score > best[i].score:
                best[i] = m

    address_hit = _address_match(party, entries)
    if address_hit and (address_hit.csl_entry_id not in {m.csl_entry_id for m in best.values()}):
        best[len(best)] = address_hit

    matches = sorted(best.values(), key=lambda m: -m.score)[:5]
    status = "exact_hit" if any(m.listed_record["exact"] for m in matches) else "fuzzy_hit" if matches else "clear"
    lists_at = csl.downloaded_at()
    if matches:
        top = matches[0]
        eid = ledger.add(f"CSL screening of {party.role} '{party.name}': {status} vs '{top.listed_name}'",
                         {"score": top.score, "breakdown": top.breakdown, "list": top.listed_record["source"]},
                         f"csl:entry/{top.csl_entry_id}", lists_at)
    else:
        eid = ledger.add(f"CSL screening of {party.role} '{party.name}': clear",
                         {"candidates_checked": len(candidates)}, "csl:none", lists_at)
    ids = [eid]
    if lists_at is None:
        ids.append(ledger.add("Only the demo restricted list is loaded; the official lists were not checked",
                              None, "csl:lists"))
    elif store.is_stale(lists_at, config.SCREENING_LIST_MAX_AGE_DAYS):
        ids.append(ledger.add(f"Restricted lists are out of date: downloaded {lists_at:%d %b %Y}",
                              lists_at.isoformat(), "csl:lists", lists_at))
    if is_forwarder:
        ids.append(ledger.add(f"'{party.name}' is a freight/logistics company", True, "screening:forwarder_keywords"))
    if (party.country or "").upper() == "IN":
        ids.append(ledger.add(
            "DGFT denied-entity status was not checked"
            + (f" for IEC {party.iec}" if party.iec else "; no importer-exporter code was on the order"),
            party.iec, "dgft:iec"))
    return ScreeningResult(party_role=party.role, party_name=party.name, status=status, matches=matches,
                           is_forwarder=is_forwarder, evidence_ids=ids)


_NUMBER_RE = re.compile(r"\d+[a-z]?")


def _address_match(party: Party, entries) -> Match | None:
    """A listed address is its own hit, even when the company name is new.

    Only a *specific* listed address can match: it must carry a unit, plot, office or PO box number that also
    appears in the buyer's address. A bare area ("Jebel Ali Free Zone, Dubai") is shared by thousands of real
    companies, and token_set alone scores 100 whenever the listed words are a subset of the buyer's.
    An address match is a close match for the officer to compare, never an exact hit (that needs the name).
    """
    addr = (party.address or "").strip().lower()
    if len(addr) < 10:
        return None
    addr_numbers = set(_NUMBER_RE.findall(addr))
    country = (party.country or "").upper()
    best: Match | None = None
    for e in entries:
        if country and e.countries and country not in e.countries:
            continue
        for listed in e.addresses:
            low = listed.lower()
            numbers = set(_NUMBER_RE.findall(low))
            if len(low) < 10 or not numbers or not numbers <= addr_numbers:
                continue
            score = round((float(fuzz.token_set_ratio(addr, low)) + float(fuzz.token_sort_ratio(addr, low))) / 2, 1)
            if score < config.SCREEN_FUZZY_SCORE:
                continue
            exact = False
            m = Match(csl_entry_id=e.id, listed_name=e.name, score=score,
                      breakdown={"address": round(score, 1)},
                      listed_record={"source": e.source, "name": e.name, "addresses": [listed],
                                     "countries": sorted(e.countries), "exact": exact, "address_match": True})
            if best is None or m.score > best.score:
                best = m
    return best


def reload() -> None:
    """Drop cached list data (after downloading a fresh CSL)."""
    csl.load.cache_clear()
    _index.cache_clear()
