# Clearance: one place for a compliance officer

Local notes on `dev2`. Not pushed. This is the job, the algorithm as it stands after the rule changes, the lists on disk, and what the officer should see and do on each order before they override.

The product recommends. The officer signs a release or a block, or overrides with a written reason. The original recommendation stays in the audit.

## What the officer does

1. An order arrives. Read the part, the quantity, the buyer, the end user, any middleman, the shipper, the destination, and what they say the part is for.
2. Identify the part. If the part number is unknown, read the datasheet wording. If it still is not a known family, stop.
3. Screen every party’s name and address against the ban lists.
4. If the buyer is in India, check the importer-exporter code on DGFT. There is no file for this. The officer does it and records the result.
5. Ask whether this buyer can use this quantity. A factory is judged on its technical staff. A distributor is judged on headcount, then on the named end user.
6. If the story is thin or risky, ask for an end-use letter: who uses it, what it is built into, which country. One follow-up. A vague reply does not clear a buyer who cannot use the quantity.
7. If a licence is required, list the documents. The officer collects them. The product does not file with the government.
8. Note what only the order can show: a price that is too high, payment from another country, a house or a virtual office as the ship-to.
9. Sign release or block, or override. Save the file.
10. After a signed release, watch that buyer. The next order is reviewed again. The signed order is not reopened.

## Lists on this machine

Git-ignored. Rebuild notes are in `data/csl_manifest.txt`.

| File | What |
|---|---|
| `data/csl.csv` | US Consolidated Screening List. 18,598 companies, vessels, and aircraft. Individuals removed. SDN, Entity List, Denied Persons, ITAR debarred, and the other US lists in that download. |
| `data/sanctions_extra.csv` | Entities only. UN 274, EU financial sanctions 1,779, UK sanctions 1,667. Built by `scripts/build_sanctions_extra.py`. |
| `data/csl_demo.csv` | Two synthetic names so the demo never calls a real unlisted company suspicious. Always loaded. |
| `data/catalog.csv` | Eight demo parts. A datasheet phrase can map an unknown part number onto one of these families. |
| `data/licence_rules.csv` | SCOMET and EAR, part category by destination. |
| `data/demo_crustdata/` | Synthetic company, people, and peer JSON. Used when the name matches a demo firm. |
| `.env` | `CRUSTDATA_API_KEY`. Not committed. |

India’s Denied Entity List is not a file. The audit says it was not checked unless the officer records a lookup.

## Algorithm changes

Lower score is better. Under 30 is `consistent`. 30–59 is `medium_risk`. 60 or more is `high_risk`. No record, or a record with no description, headcount, or people, is `no_data` and a hold. It is not a pass.

Checked against 25 real manufacturers and distributors (Analog, TI, Infineon, NXP, ST, Microchip, Renesas, onsemi, Qorvo, Skyworks, Broadcom, Vishay, Keysight, TE, Bharat Electronics, Tejas, Tata Elxsi, Cyient, Astra Microwave, Centum, Digi-Key, Mouser, Arrow, Avnet, Future). None are small. The smallest headcount was 1,724. Ten thousand cheap FPGAs was a normal buy for all of them. Hiring data was missing for five real firms, so a missing careers page is not a penalty.

### Buyer type

Workforce first. Engineering share about 40% or more means manufacturer. Description says distributor, wholesale, or trading, and engineering is under 40%, means distributor. A 25-person sample is only a backup. The description alone is last. The words “design” and “manufacturing” are not proof of a factory. Digi-Key’s industry label is “Electronics Manufacturing.”

### Scored

| Rule | Points | Meaning |
|---|---|---|
| `C1_not_a_technical_business` | up to 40 | No hiring, news, description, or past-employer trace of this work, and engineering share is under 25%. Fades to 0 at 25%. Vishay is about 28% and TE about 31%, so they are not caught. |
| `C2_low_engineering_share` | up to 20 | Engineering share versus peers. 20 at the 0th percentile, 0 at the 50th. No cliff at the 10th. |
| `C3_small_staff` | up to about 20 | Small headcount, not age. Fades to 0 at 80 people. If the sample covers at least 70% of the staff, points rise by about a third. |
| `C4_headcount_decline` | 10 | Headcount down more than 20% in a year. |
| `O1_quantity_vs_technical_staff` | up to 20 | Quantity versus technical headcount times the part’s per-person allowance. Full points at 5× a reasonable order. Ten thousand high-end parts (5 per person) is normal only around 2,000 engineers. Ten thousand cheap FPGAs (50 per person) is normal around 200. |
| `D1_small_staff` | up to about 34 | Same small-staff fade, for a distributor. |
| `D4_large_order_small_distributor` | up to 15 | Distributor version of quantity. The catalog cap is what about five people can move. It scales with headcount. |

There is no purchase-order feed. “They do this work” is hiring, news, the description, and past employers.

### Written on the file, not scored

- `C5` / `D3` traffic versus peers: value, median, range, percentile, example peers, industry, country.
- `D2` headcount versus peers, same detail.
- Ship-to country different from the buyer. `transshipment_hub` for AE, HK, TR, SG. `different_country` otherwise.
- Company age.
- For an Indian buyer: DGFT denied-entity status was not checked, plus the IEC if one was typed.

### Decision order

First match wins.

1. `R1` exact name or address hit → block.
2. `R2` part still unknown after datasheet wording → hold.
3. `R3` fuzzy name → hold.
4. `R4` end user is a freight forwarder → hold.
5. `R5` order still incomplete → hold.
6. `R5b` unusual price, virtual or house ship-to, or payer in another country → hold.
7. `R6` no or thin company data → hold.
8. `R7` medium or high risk and no end-use reply yet → ask.
9. `R8` reply vague, evasive, or no real end user → hold.
10. `R9` reply is fine but the buyer is still high risk → hold.
11. `R9b` controlled part, and the buyer still has C1, O1, or D4 → hold. Naming a use does not clear it.
12. `R10` model unavailable for a required step → hold.
13. `R11` licence required → licence required. Documents are listed. Nothing is filed.
14. `R12` otherwise → release.

A close address match (about 90 or better, same country when a country is known) is its own block, even if the name is new. Live people search no longer sorts on a field Crustdata rejects.

## One order, before override

The officer should see all of this, then sign or override. Override does not delete the recommendation.

- Recommendation, rule id, and plain-language reason.
- Parties: role, name, country, address, IEC if any. Screening result. On a hit, the order side and the listed record side by side, including address hits.
- Part, quantity, datasheet sentence, controlled or not, licence or not, documents still to collect.
- Buyer: coverage, manufacturer or distributor and which fact decided it, technical headcount, reasonable quantity, ordered quantity, points that fired, and the notes that did not score.
- End-use: claimed use, named end user, that end user’s screening and capability, vague or not, follow-ups sent.
- Order red flags: unusual price, who paid, virtual or residential ship-to. Empty until the officer sets them.
- Evidence list with sources. Downloadable audit.
- Signature line and any previous override.

## What they can do from here

- Sign a release or a block. Nothing ships or is refused before that.
- Override to release, hold, licence required, or block, with a required reason.
- Correct a name, address, or country and run the file again.
- Paste datasheet wording for an unknown part number and run again.
- Type an IEC and mark the DGFT lookup clear or denied.
- Mark unusual price, third-country payer, or a house or virtual office.
- Send the end-use request and the one follow-up. Paste a reply that arrived outside the mailbox.
- Mark licence documents as collected. Not filed with DGFT or BIS.
- Open the audit.
- On a signed release, see the buyer on the customer list. A later change reviews the next order only.

Queues: ready to sign (release and block), needs a person (holds, fuzzy names, address hits, missing end user, quantity the buyer cannot use, IEC still unchecked), and customers.

## Not in the data

Price versus market, who pays, a house or a virtual office, and whether this exporter has sold to this buyer before. The officer marks those on the order. They are not inferred.
