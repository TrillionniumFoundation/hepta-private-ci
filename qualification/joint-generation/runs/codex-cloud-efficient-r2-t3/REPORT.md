# r2 training/validation t3 — control net benefit still unverified

Balanced execution actually ran in the same configured Codex Cloud environment.
Source `5c33a5373a`, frozen receipt commit `ac42472306`, train exit **2**. Formal
r2 test construction/opening never occurred; r1 remains sealed. All 15 selected
models changed encoder/text/image parameters and retained their fixed decoder.

All complete systems stayed within the unchanged 12B operator and10 CPU-second
caps. Attributed CPU: CE8.135, anchor8.581, additive9.221, NDU9.014, control9.135s.
Phase telemetry contains154 phases, maximum GC pause4.07ms. This run did not
reproduce the prior seconds-long service spike; its historical cause is unknown.

Validation differences are development evidence, not held-out acceptance:

| Comparison | Task utility | Joint success |
|---|---:|---:|
| additive−same-weight CE | +0.021224 | +0.022018 |
| NDU−additive | +0.006639 | +0.006875 |
| control−cheaper single random view | +0.020809 | +0.022230 |

The effective reference is NDU/full. Complete CPU-net control−reference is
**−0.004409**, so readiness failed. NDU/full rawutility0.963048; control content
always-full0.958934, selected control0.956801. Control selected366 updates/seed
versus NDU386, then routing reduced raw utility by another0.002133. Control mean
CPU attribution138139ns versus NDU154666ns did not compensate. Actual generation
component12242/13845ns and output encoding125516/140121ns are retained separately;
all components remain included. Maximum greedy drop0.010417 passed0.02, corruption
controls passed, and budget violations were zero.

The present controller compares an entropic gain with0.02 while primary J_H
uses rawutility and actual complete CPU normalized by full service. A prospective
controller-law revision must align its gain/cost units on training-only data,
include branch-dependent output encoding and all critic/calibration/build cost,
and receive a new freeze. It cannot reinterpret this failed law as passing.
Unused budget can fund actual selected-model training only with original Adam/RNG
state and complete revalidation/export costs; static baselines receive the same
rule. No price, budget cap or qualification gate may be lowered.
