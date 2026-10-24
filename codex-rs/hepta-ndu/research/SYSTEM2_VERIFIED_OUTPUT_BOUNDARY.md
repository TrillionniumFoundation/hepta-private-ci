# Reader output boundary: an independent, closed-world positive control

Stacked research under [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546); **NOT a production or learned NDU/Reader improvement**. This audit is anchored in two *completed*, not queued, GitHub Actions Reader runs:

| Source | Hosted run | Artifact | External ZIP SHA256 |
|---|---|---|---|
| Original 100 fixed multi-hop answers | 38230686420 | 11743040489 | `7a0cb798418e7b00ac5258c26617f05e547be9f4c428bb82fb13428ec98647e2` |
| 180 new prompt-variant answers + 60 untouched controls | 38251877267 | 11751525542 | `ff8caeea43ad029167d52107947b483a44e77e60aa92927211626ef105e935b7` |

Original frozen prompt source: `7784872ebb8936865b4245f423d3aa2bb9e0a39d`; prompt-variant generating source: `98828b2f8d616856a50ca7a1abf44292a1f060e1`. The original 180-answer seal is `2782f91d086c81bbd8434ff64b6533dbb57666acced0217af60b1899b146aa4e`.

## Scientific distinction: source verification is NOT neural compliance

On the **same 20 synthetic English questions** under three evidence conditions, the original Reader and three new prompt formats produce **240** exposed answer rows. All 180 new calls succeeded on the pinned unchanged Reader, original 60 calls are reused. All 12 conditions have **zero strictly grounded answers**: no valid independent Reader citations and no correct exact refusals.

A *read-only, no-new-Reader-calls* control then applies a bounded symbolic verifier. It scans only the **actual delivered** selected source excerpts, parses the published fixed synthetic grammar and follows its project→unit/device→token path. It accepts a Reader-produced answer token ONLY when the raw answer has exactly one token occurrence and it equals the unique value entailed by the path; it then creates a **separately marked system-authored** `[E#]` citation for each actual original source. All other cases produce an **external system refusal**, not a model-generated refusal. The policy does not read `Case.answer` or required source labels to decide; gold is used solely after predictions are frozen for a cross-check. Neither the model answer, model prompt nor baseline artifact is edited.

The *fixed grammar program*, not a learned model, can fully traverse all 20 positive questions by construction. Thus it is a strong positive control and **not a general semantic grounding certificate**.

### Completed local exact-source diagnostic

All 24 prompt-archive internal SHA256 entries and the original 22-member archive validated. Every published raw question, source span, Reader identity, token/profile digest, 180-call census and original archived per-answer score replayed without a new model call. Standalone local tests: **14/14 passed** on Python 3.13. The local test environment uses an exact synthetic-source slice and minimal nonproduction shims for two unavailable repository modules; the hosted workflow runs the **real repository modules** and is the authority for those integration tests.

| Reader prompt | Full source paths (20) | Actual Reader grounded+cited | Externally certified system answers | Incomplete-evidence unsupported correct token |
|---|---:|---:|---:|---:|
| Original | 20 | 0 | 1 | 11/20 |
| Direct | 20 | 0 | 2 | 3/20 |
| Demonstrated | 20 | 0 | 0 | 0/20 |
| Compact | 20 | 0 | **15** | **10/20** |

External-system absence-of-evidence controls become 20/20 strict refusals in BOTH no-evidence and premise-removed arms of every prompt variant. That is enforced by the grammar boundary, **not learned refusal behavior**. At compact positive controls, 5/20 responses are externally refused despite an existing path because the raw Reader token is wrong or ambiguous. The pure symbolic source-only oracle-free control would answer 20/20 of these grammar cases and does **not** require a Reader at all.

The prompt study additionally revealed widespread **JSON prefix continuation**: in the direct and demonstrated no-evidence conditions, 20/20 responses each began with the JSON request syntax rather than the requested refusal. Demonstrated full-evidence and missing-premise conditions were also 20/20 JSON echoes and all 20/20 saturated the 64-token decode budget. Compact format reduced truncation and gave more correct literals, but **did not fix citation/refusal**. These are source-format and model-adequacy diagnostics; the corpus was already exposed and compute costs differ across formats.

## Mandatory boundaries and next decision

The external boundary may be valuable for a **strictly typed, closed-domain extraction system**, but does not make the frozen neural Reader capable of properly citing or refusing. Its parser must be validated independently against adversarial natural documents before considering any broader use. Do NOT report system-minted citations as Reader citations, or count system-minted refusals as Reader safety training wins. No semantic sufficiency, NDU/FBSDE continuation value, Riccati speed, general language transfer or multimodal transfer is demonstrated. Production is not accepted.

The next learning-science priority is the actual **single-hop** Reader adequacy study and the independent 128-token output-cap study. If those also fail, use a stronger frozen Reader and matched prompt/compute controls rather than growing Cell or FBSDE complexity.

## Reproduce

Pin both archives with their exact published GitHub SHA256. In a checkout of the exact research head, run:

```sh
PYTHONPATH=scripts/memory_cell python scripts/memory_cell/system2_reader_proof_boundary.py \
  /tmp/multihop-100.zip /tmp/prompt-180.zip /tmp/verified-output-audit.json
python -m unittest discover -s scripts/memory_cell -p 'test_system2_reader_proof_boundary.py' -v
```

The new CI is model-free, downloads the externally pinned completed artifacts, exercises the real original-byte evidence modules, rejects any archived score/proof/identity drift, writes an auditable SHA256 source-and-output manifest, and retains the full 240-row provenance receipt. Separately, the inherited full research workflow still runs all existing model-family tests and lint. Both are separate from claimed production acceptance.
