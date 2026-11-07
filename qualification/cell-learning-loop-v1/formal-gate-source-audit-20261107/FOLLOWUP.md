# Source and cost follow-up — HOLD

This is an additive read-only audit. The original audit, training protocol, thresholds,
receipts and unsuccessful result remain unchanged. No model or training was run for
this follow-up.

## What was recovered

The original [V13 latency record](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/evidence/run/LATENCY_COST.json)
was retrieved and verified: 924,270 bytes, Git blob
`cc6e36aaa3243306084f55accca632a57ad8338a`, SHA-256
`e7cad4429e948a37f413043090d4beb0b7dc53379b118ea274fd92291ada5285`.
[COST_DENOMINATOR_READBACK.json](COST_DENOMINATOR_READBACK.json) preserves the
recomputed census and the recorded resource boundaries.

| Recorded scope | Exact denominator or cost | Interpretation |
| --- | --- | --- |
| Timed method trials | 72 authored requests × 6 methods × 3 repeats = 1,296 | Every tuple appears once; repeats are not independent source tasks. |
| Timed encoder calls | 864 | Four encoder methods × 72 requests × 3 repeats. |
| Warmup | 6 rows, 4 encoder calls | Separate from the timed trials. |
| Common training feature encoding | 120 rows; 0.583176657994045 wall seconds | One shared setup item, not six independent encoders. |
| Entire fixed setup | 1.0476219190022675 wall seconds; 1.038763745 CPU seconds | Includes its component setup measurements. |
| Whole profiler envelope | 6.9486532250011805 wall seconds; 6.933707602 CPU seconds | Includes inner records; do not add those again. |
| Profile snapshots | 3 projects × 4 linked frontiers = 12 | Not 12 independent projects. |
| Recorded checkpoint storage | 81 files; 18,558,416 bytes | Census from the original record; this audit did not refetch all 81 files. |

The profiled checkpoint is `5f28dbda0393259005091a2fde9f56dd99837f4667e4924affd9906e8b0f7719`.
Its 0.06381438499374781-second adapter fit is different from this loop's parent
`1b5091f1d5a920bddf57999367d60aa56116f2040da933cb8afc2b330c5e4455` and its
recorded 0.07970184599980712-second fit. These figures must not substitute for one
another. The [original cost audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1/qualification/memory-cell-v13/evidence/AUDIT_COST.md)
explains the warm resident scope and exclusions. Transport, queueing, cold startup,
source acquisition, full training/search amortization, recovery and energy remain
outside that timing measurement. No full lifecycle cost claim follows from it.

## Source provenance is more precise, but the original gate is still unbound

The frozen `EXECUTED_SOURCE/prepare_run.py` (SHA-256
`7a6c86dd351b3d08acb55bf7d7bb4af40d8389eadd76e8079359ab5062ca4fe4`) reads
`donor/qualification/memory-cell-v13`; its `donor_head` is that donor checkout's
HEAD. Thus `0abc3f5132c944d517e6a75d6d5362819fd285ec` does not itself identify
V15 gate code. The commit lookup still returns “No commit found”. Bounded local,
default-branch code and repository/organization metadata searches did not recover
an original mapping; this does not prove absence from all possible storage.

Two actual V15 reference versions were recovered by immutable commit and file hash:

- [Base admission.py at 379c21c2](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/379c21c2e625c3a3dfbb514e11b9e8fe2213cda8/qualification/memory-cell-v15/admission.py), Git blob `23618c4366a71c319640742e5f080021f916f15c`.
- [Cohort admission.py at c8a8bdc5](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684/qualification/memory-cell-v15/admission.py), Git blob `4a0289ba33e3163e497d4d163a7a288666d206be`, with [cohort.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684/qualification/memory-cell-v15/cohort.py), Git blob `a97615a752e9aa25e7480a1d48eab5f021d70c34`.

These define `MatchedEvaluator`, not a verified source mapping for the old loop's
named `FutureAdoptionGate`. The later cohort implementation adds phase isolation,
source-unit identity, a fixed comparison roster, information parity and bounded
monitoring looks. It is a possible reference for a separately frozen prospective
protocol, not evidence that the old nine-arm gate was registered or executed.
`evaluate` invokes predictor callbacks after collecting refusal reasons; it must
not be used as a read-only readiness check on hidden tasks.

## What still blocks P1

The original 1-candidate protocol has consumed 1 attempt and has **0 remaining**.
Broad research authorization already exists. A later prospective protocol must
carry the complete previous attempt/failure/exposure ledger and cannot reset its
cost basis. The original 48-case calibration gate and later 72-case no-loss replay
remain separate. The authored gain from 0/2 to 2/2 did not erase the 59/72 to 55/72
replay regression, and no adoption occurred.

Eight fixed-revision official encoder assets are now restored with exact byte
verification, and a new isolated runtime preserves the declared Python/package
versions. Those preparations have their own recorded costs; the new interpreter
binary is a new frozen boundary, not recovered proof of the historical binary.
They do not repair source authorization at owner revision 2, create an independent
natural future cohort, reconstruct historical bills/energy/network/retained-byte
costs, or authorize publication of a stale historical parent.

A useful next step is a complete prospective manifest with the current owner/source
cut, exact gate implementation/settings, finite budget, exposure history, fixed
comparison and information rosters, and a common cost horizon. Missing historical
measurements stay null and continue to block full-cost adoption. New natural source
units must arrive after the freeze. Repeated authored cases, a new directory and P2
engineering fixtures cannot become previously unseen natural tasks.

The machine-readable [FOLLOWUP.json](FOLLOWUP.json) contains exact source pins,
recoverable preparations and the remaining blockers. No threshold, authority or
old evidence was changed.
