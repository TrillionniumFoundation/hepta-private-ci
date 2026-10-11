# Native Stem shadow-scale experiment: negative gate, not deployment

**Source run:** [38135216246](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38135216246) (completed **success**).  
**Actual source commit:** `953c65d9cf9a79dbd3e6543e2177a6a6ef61ed9c`  
**Source Git tree:** `4c57c214109b756ff97415c1f235a7250e4b9a6f`  
**Immutable artifact ID:** `11700958394`; **ZIP SHA256:** `3fe286f84d7f719ebe9ee300d3772aec1842dafb5c97ab9dfdb792eb4daaf43c`  
**Integrity:** 146/146 internal SHA256SUMS entries verified independently from downloaded bytes.

## The actual result

The full experiment completed 576/576 ordinary forced-top1 six-arm Reader policy
answers under strict pre-retrieval as-of source admission. **Separately** it
retained 30 Head-and-Cell *TRAIN-only* residual-scale fits and 480 label-blind
shadow candidate selections (no Reader call). The scalars were chosen from
the preregistered `0,1,2,4,8,16,32,64` grid using only admitted TRAIN weak
native-document support. Held-out native support labels were opened only
after all shadow selections were fixed.

For the **final checkpoint (48)**, the source-only results collapsed over two
Cells and compared with the exact original frozen top1:

| Arm | TRAIN-chosen residual scale (general / temporal) | test labelled-source gain / regression | transfer gain / regression |
|---|---|---:|---:|
| Prototype | 0 / 0 | 0 / 0 | 0 / 0 |
| Linear | 16 / 0 | 1 / 1 | 0 / 2 |
| Gated | 16 / 64 | 1 / 1 | 0 / 4 |
| Lineage LoRA + gated | 16 / 64 | 1 / 1 | 0 / 4 |
| Independent LoRA + gated | 16 / 64 | 1 / 1 | 0 / 4 |

The five arms each had exactly **8 original test and 8 original transfer
questions**; each phase has **6 or 7 answerable native-document support
annotations**, not independently verified window entailment. Although residual
amplification changed actual source top1 choices, NONE of the final-checkpoint
learned candidates improved net weak support in both phases. In particular,
test examples favorable to scaling cannot be presented while concealing the
transfer regressions.

At 16/32/48, many test/transfer rows repeat the SAME 16 original questions:
30 calibration fits and 480 choices are **not 480 independent subjects**.
A source-only net-gain criterion is only a *rejection* and potential planning
diagnostic, never a production pass condition or independent statistical result.
No shadow Reader generation took place, and any reported positive source
label is weak native **document-level** support, not an independently adjudicated
entailment or valid citation.

## Repeatable, fail-closed evidence

`scripts/memory_cell/stem_shadow_negative_gate.py` verifies both original
archive ZIP hash and complete internal manifest, original commit/tree, the
entire 30-calibration and 480-choice identity census, same original Head
snapshots, scales selected TRAIN-only, unaltered original source pool, zero
additional Reader calls, and the published per-phase support-gain/regression
census. The associated hosted workflow downloads artifact `11700958394`
and retains source, tampering tests, full audit JSON, and failure logs.

**Decision:** do not promote any amplified residual Head to a live/Reader
comparison or expand Cell count based on cherry-picked test flips. To establish
actual improvement requires a new pre-registered model/policy comparison,
genuine held-out source-family and future-window tests, independently reviewed
semantic citation support and complete p95/dollar/energy cost. This archive
supplies **no** independent semantic citation precision denominator.
`production_accepted=false` throughout.
