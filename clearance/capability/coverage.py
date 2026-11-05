"""Coverage go/no-go report (task A3).

    python -m clearance.capability.coverage                     # companies in data/test_companies.csv
    python -m clearance.capability.coverage acme.com "Some Co"  # any domains or names (live needs CRUSTDATA_API_KEY)

Prints missing/thin/rich per company plus the fields that drive scoring. Every call is cached, so re-runs are free.
"""
from __future__ import annotations

import csv
import sys

from clearance import config, crustdata_client
from clearance.capability import assess
from clearance.evidence import Ledger
from clearance.models import Party


def main(keys: list[str]) -> int:
    client = crustdata_client.get_client()
    print(f"source: {'LIVE Crustdata + fixtures' if client.live else 'fixtures only (no CRUSTDATA_API_KEY)'}\n")
    print(f"{'company':38s} {'coverage':8s} {'type':12s} {'headcount':>9s} {'people':>6s} {'peers':>5s}  tier")
    counts = {"missing": 0, "thin": 0, "rich": 0}
    for k in keys:
        r = assess(Party(role="buyer", name=k, domain=k if crustdata_client.is_domain(crustdata_client.norm_key(k)) else None),
                   [], [], "", Ledger())
        counts[r.coverage] += 1
        f = r.features
        print(f"{k[:38]:38s} {r.coverage:8s} {r.buyer_type:12s} {str(f.get('headcount', '-')):>9s} "
              f"{str(f.get('people_sampled', '-')):>6s} {str(f.get('peer_count', '-')):>5s}  {r.tier}")
    print(f"\n{counts}. Go if most demo buyers are 'rich'; otherwise switch demo buyers (AGENTS §11).")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        with open(config.DATA_DIR / "test_companies.csv", newline="") as f:
            args = [r["domain"] or r["name"] for r in csv.DictReader(f)]
    sys.exit(main(args))
