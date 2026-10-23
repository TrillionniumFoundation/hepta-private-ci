# Calculated feasibility and remaining uncertainty

The single source/table analysis command exited0. It trained no model, performed
no content/decoder forward, and sampled/rendered nothing. Its bound inputs and
full operator quotes are in
[`analysis.json`](../runs/content-joint-architecture-analysis-v1-20261023/analysis.json).
The calculator is [`analyze.py`](analyze.py); these are prospective estimates
for the new architectures, not measured implementation receipts or CPU speeds.

| Quantity | Existing independent two12 heads | Proposed native12 | Analytical general144 |
|---|---:|---:|---:|
| Head parameters | 792 | 396 | 4,752 |
| All active content parameters | 7,288 | 6,892 | 11,248 |
| Total including fixed decoder | 9,784 | 9,388 | 13,744 |
| Theta + gradient + two moments, bytes | 233,216 | 220,544 | 359,936 |
| Head probability buffer, batch64 bytes | 12,288 | 6,144 | 73,728 |
| S/H update, batch64 units | 2,248,286 | 2,069,850 | 4,048,974 |
| A update, batch64 units | 2,300,130 | 2,080,222 | 4,143,826 |
| N update, batch64 units | 2,307,106 | 2,084,898 | 4,190,742 |
| Forward + sampling + one RGB decode, units/request | 19,236 | 18,242 | 29,206 |

Native12's quoted reductions are7.94% for H updates,9.56% for A,9.63% for N;
the144 quote increases them by80.09%,80.16%,81.64%. Service arithmetic quotes
exclude non-arithmetic primitives; actual full CPU includes validation, setup,
allocation/memory, PNG, JSON, hashing, return and export and is **unmeasured**.
No fresh runtime benchmark or extrapolation from e7de component timings was made.
The future executable implementation must substantiate the draft inventory.

One reason the utility reduction is larger than the parameter reduction is
categorical structure: the independent objective computes conditional products
over144 joint cells; native12 uses its12 actual joint states directly. The full
original external R and all pixel observations remain retained and billed.
General144 has a flat utility but a much larger dense projection/backpropagation.
It produces the same twelve RGB images, not144 distinct images.

Saved decoder evidence covers all twelve classes in every seed. The minimal
nearest-template margins for11/23/47 are.01981016/.01981382/.01981518; all exceed
the uint8 pairwise margin bound.00392157. Every one of the4,752 checked
target/off-diagonal comparisons has a dominating agreeing caption with the same
image, minimum reward gain.05. Each unrestricted reward argmax is(y,y).
These facts support the legal restricted support; they are not new model gains.

## Complete build, rather than a cheap-head-only claim

The separate new TRAIN draft retains10 CPU seconds/12B per objective family,
covering six fixed paired models (two recipes × three seeds), all shared base
preparation and all observations/exports/service. It has no LR/architecture
search. The common immutable base provenance already costs3.486924537B and
2.075925876 CPU seconds, fully attributed to every family despite file reuse.
New four-group native ABI compilation/initialization/checks add unknown actual
costs. The current native ABI cannot accept four groups; it is not implemented.

Before those extra costs, reserving2 CPU seconds/500M for observation/export/
service leaves at most1.335512577B and.987345687 CPU seconds per recipe/seed.
Unit-only upper bounds on useful updates, ignoring the potentially binding CPU
cap and extra setup, are:

| Objective | Independent | Native12 |
|---|---:|---:|
| S / H | 594 | 645 |
| A | 580 | 642 |
| N | 578 | 640 |

These are admission ceilings for a proposal, not promised update counts or
permission to start a new run. Actual common costs reduce them. A failed
preflight/reserve/cap is preserved; no cap or candidate count is increased.

The old e7de cumulative ledgers remain H11.847956433B/6.590750701 CPU seconds
and A11.847662223B/6.937385920 seconds. Their remaining unit allowances are only
152.043567M/152.337777M. The six-model plan cannot be appended with a reset;
it is a proposed distinct TRAIN protocol requiring the parent's unified design.
Old static results retain their own complete construction/search budgets. A
portfolio selecting old plus new models must pay their union, deduplicating
shared provenance, before making any whole-budget superiority claim.

The falsifiable content question is native A−H **after the same coupling**,
against strong native/independent pure CE and fixed static reconciliation,
with zero-update coupling controls. A nonpositive A−H mean CE or joint-success
change rejects that developmental training hypothesis. No formal confirmation,
dynamic win or NDU improvement follows from this cost analysis.
