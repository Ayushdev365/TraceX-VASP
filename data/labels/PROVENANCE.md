# Label dataset provenance

The labelled-address dataset is the single most important asset in this system's accuracy
(DPRD §16, §47(22)). A wrong or fabricated label does not degrade gracefully — it produces a
confident attribution pointing at the wrong company, which is precisely the failure that
could cause wrongful action against an innocent party (DPRD §27 F07).

So this project has one hard rule:

> **Never invent a VASP address, and never present an unverified label as verified.**

It is enforced in three places, not just stated here:

1. **The database.** `vasp_addresses.source`, `source_url` and `source_tier` are `NOT NULL`.
   A `CHECK` constraint rejects `verification_status = 'verified'` without a `verified_at`
   date, and another rejects any `demo_unverified` row claiming to be verified.
2. **The importer.** It reads only what `manifest.yaml` declares, and fails the *entire*
   import — writing nothing — if any row lacks provenance, has an address that is invalid or
   non-canonical for its chain, or claims verification it cannot support.
3. **The attribution engine** (Phase 8). A candidate supported only by `demo_unverified`
   labels is refused, returning "No reliable VASP attribution found" rather than a number.

---

## Reliability tiers

| Tier | Meaning | Default reliability | Examples |
|---|---|---|---|
| `official_vasp_published` | The VASP itself published the address | 1.00 | Exchange compliance disclosures, proof-of-reserves attestations |
| `sanctions_list` | An official designation naming the address | 1.00 | OFAC SDN, OpenSanctions |
| `community_verified` | Community-sourced **and** independently spot-checked by us, with the check recorded | 0.75 | A public label set whose entries we confirmed against on-chain behaviour |
| `community_unverified` | Community-sourced, not independently checked | 0.55 | Public label repositories taken as-is |
| `demo_unverified` | Synthetic or unconfirmed; development and demo only | 0.25 | The fixture below |

Promotion from `community_unverified` to `community_verified` requires a recorded
`verified_by` and `verified_at`, and the method of verification noted in the row's `notes`.
Promotion is never automatic and never a bulk operation.

---

## Active sources

### Synthetic demo fixture

**Status:** active, opt-in only.
**Tier:** `demo_unverified`. **Files:** `demo/demo_vasp_addresses.csv`,
`demo/demo_risk_entities.csv`. **Generator:**
`backend/app/database/seeds/demo_fixtures.py`.

This is **not real data.**

- The service providers are **fictional** — "DEMO — Meridian Digital Exchange", "DEMO —
  Kavach Custody Services", "DEMO — Northwind OTC Desk", "DEMO — Obscura Mixer", "DEMO —
  Causeway Bridge", "DEMO — Rollhouse Casino". None is a real company. No fabricated address
  is attached to any real exchange's name, because that would be a false factual claim about
  a real business.
- The addresses are **derived deterministically** from documented seed strings —
  `sha256("VASPTrace/synthetic-demo-fixture/v1|<chain>|<seed>")`, first 20 bytes — and then
  formatted as a valid EIP-55 or Tron base58check address. They are not copied from any
  blockchain. Anyone can re-run the generator and confirm the files byte-for-byte.
- They exist so Phases 6–9 have something to develop and test against, and so the demo has a
  path that reliably terminates at a VASP.

**Guardrails:** imported only with `ALLOW_DEMO_LABELS=true` or `--allow-demo`; refused when
`APP_ENV=production` (the config layer raises at startup); cannot support a primary
attribution; every trace relying on them is labelled in the UI, the JSON report and the PDF.

---

## Sources under consideration

None are active yet. This is an open decision — see `docs/IMPLEMENTATION_PLAN.md` §5, Q1.

| Candidate | Gives us | Does not give us | Licence question |
|---|---|---|---|
| **OFAC SDN** digital-currency addresses | High-reliability *risk* labels: designated addresses, sanctioned mixers | Almost no exchange/VASP coverage | US Government work, public domain — usable |
| **OpenSanctions** crypto addresses | Broader sanctions coverage, structured bulk data | Same gap: risk, not VASPs | CC-BY-NC; **non-commercial clause needs review before Pilot** |
| **Public community label sets** (GitHub label repos, explorer-derived exports) | The exchange deposit/hot-wallet coverage the product actually depends on | Unverified; quality varies by entry | Per-repository; must be checked individually |
| **Exchange-published addresses** | The highest-reliability VASP labels | Only a handful of exchanges publish them | Generally permissive when published for this purpose |
| **I4C / LEA-confirmed attributions** (Pilot) | Ground truth (DPRD §16 "highest") | Not available pre-Pilot | Requires I4C agreement and legal review |

The honest position for the MVP: **risk coverage can be strong, exchange coverage will be
partial.** Every trace therefore carries a coverage notice, and a non-match is reported as
"no attribution found within the current hop cap and label coverage" — never as "this wallet
has no VASP relationship".

---

## Adding a source

1. Put the CSV under `sanctions/`, `community/` or `demo/`.
2. Add an entry to `manifest.yaml` with all seven required fields, and bump `version`.
3. Document it in this file: what it is, why it got that tier, and its licence.
4. Dry run: `python -m app.database.seeds.import_labels --manifest ../data/labels/manifest.yaml --dry-run`
5. Read the integrity report. Conflicts are warnings for review; malformed addresses and
   unsupported verification claims are failures that block the import.
6. Import for real by dropping `--dry-run`.

### CSV columns

`vasp_addresses` — required: `vasp_slug`, `vasp_name`, `vasp_kind`, `chain`, `address`.
Optional: `jurisdiction`, `website`, `nodal_officer_channel`, `legal_entity`,
`is_fiu_ind_registered`, `address_type`, `verification_status`, `verified_by`, `verified_at`,
`reliability`, `notes`.

`risk_entities` — required: `chain`, `address`, `entity_kind`. Optional: `entity_name`,
`severity`, `verification_status`, `notes`.

`source`, `source_url` and `source_tier` are **not** CSV columns. They come from the manifest,
so a row cannot carry an origin the manifest has not declared.

---

## Freshness

Every trace reports the age of the label dataset it used. Past `STALE_LABEL_DAYS` (default
30, DPRD §21) the result carries a visible stale-dataset warning, because a result built on a
six-month-old label set does not deserve the same implied confidence as one built on a
freshly synced list.
