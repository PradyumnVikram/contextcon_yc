"""The 9 acceptance cases (AGENTS_*.md §4.9) as Order fixtures. SHARED (task S4).

Company names are synthetic. Names containing "shell" / "nodata" / "distributor" /
"Listed Electronics Trading" drive the S5 stubs. Real modules use data/test_companies.csv (A10).
"""
from __future__ import annotations

from dataclasses import dataclass

from clearance.models import EndUseClaim, Order, OrderLine, Party


@dataclass
class Case:
    name: str
    order: Order
    expected: str                      # recommendation from §4.8
    end_use: EndUseClaim | None = None  # reply to feed in, if the case needs one


def _order(oid: str, buyer: str, country: str, ship_to: str, lines: list[tuple[str, int]], **extra) -> Order:
    parties = [Party(role="buyer", name=buyer, country=country),
               Party(role="ship_to", name=buyer, country=ship_to)]
    parties += extra.pop("parties", [])
    return Order(order_id=oid, parties=parties, ship_to_country=ship_to,
                 lines=[OrderLine(part_number=p, quantity=q) for p, q in lines], **extra)


CASES: list[Case] = [
    Case("1 radar firm, small qty, no licence",
         _order("C1", "Synthetic Radar Systems", "IN", "IN", [("PA-77G-HE", 4)]), "RELEASE"),
    Case("2 radar firm, destination needs licence",
         _order("C2", "Synthetic Radar Systems", "IN", "DE", [("PA-77G-HE", 4)]), "LICENCE_REQUIRED"),
    Case("3 distributor with a capable end user",
         _order("C3", "Synthetic Components distributor", "IN", "IN", [("FPGA-C10", 200)]), "RELEASE",
         end_use=EndUseClaim(claimed_use="FPGA prototyping for telecom boards", mapped_needs=["fpga"],
                             end_user_name="Synthetic Telecom Labs", end_user_country="IN")),
    Case("4 distributor will not name the end user",
         _order("C4", "Synthetic Components distributor", "IN", "IN", [("PA-77G-HE", 50)]), "HOLD",
         end_use=EndUseClaim(claimed_use="civilian use", evasive=True)),
    Case("5 hardware firm, 3 engineers, 100 commodity FPGAs",
         _order("C5", "Synthetic Hardware Works", "IN", "IN", [("FPGA-C10", 100)]), "RELEASE"),
    Case("6 shell, 100 high-end parts, nothing matches",
         _order("C6", "Synthetic shell Traders", "IN", "AE", [("PA-77G-HE", 100)]), "AWAITING_END_USE"),
    Case("7 no Crustdata record",
         _order("C7", "Synthetic nodata Enterprises", "IN", "IN", [("ADC-12G-HE", 10)]), "HOLD"),
    Case("8 name already on the list",
         _order("C8", "Listed Electronics Trading", "AE", "AE", [("ADC-12G-HE", 10)]), "BLOCK"),
    Case("9 close spelling of a listed name",
         _order("C9", "Listed Electronic Tradng", "AE", "AE", [("ADC-12G-HE", 10)]), "HOLD"),
]
