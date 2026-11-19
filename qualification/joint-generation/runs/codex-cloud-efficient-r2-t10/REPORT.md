# Folded-adaptation r2 build: more content updates, failed dynamic readiness

Actual exit **2**, selection_ready=false. Source `62397523755e74c35324b708e2120d6e1f68887c`,
freeze/execution `9f1c2a30bb6bb835b104faca4711280c6a3bc227`. This was one actual TRAIN/validation build in the
configured Codex Cloud environment, not a formal held-out evaluation.
The formal r2 fold remains unconstructed/unopened; r1 stays sealed.

All original CPU/work caps held, greedy retention and decoder corruption passed.
The sole negative readiness mean remains NC versus the selected efficient static NDU system.

Validation mean contrasts, not held-out estimates or confidence intervals:

| Comparison | Task utility | Joint success |
|---|---:|---:|
| additive minus same-weight anchor | +0.017316017337 | +0.017954080924 |
| NDU minus additive | +0.004722618475 | +0.004877989462 |
| control minus cheaper same-weight random single view | +0.000446690712 | +0.000474402739 |

Control minus NDU complete CPU-net utility was **-0.002650369319**.
Maximum greedy drop was 0.009548611111; every decoder-corruption drop was positive.

| System | Complete CPU seconds / 10 | Declared units / 12B | Selected updates, seeds 11/23/47 |
|---|---:|---:|---|
| supervised | 9.067202295 | 11995440577 | 534 / 535 / 535 |
| anchor | 9.026515026 | 11997736703 | 545 / 546 / 546 |
| additive | 9.756826697 | 11923377005 | 595 / 596 / 596 |
| ndu | 9.766629212 | 11564568321 | 636 / 637 / 637 |
| ndu_control | 9.351370447 | 11052490314 | 490 / 475 / 402 |

The folded kernel executed actual low/full geometry for all five arms. At the
unchanged complete budgets it enabled real extra content updates: selected NDU
636/637/637 versus t9 386/386/386; NC 490/475/402 versus t9 367/367/367.
This is not evidence that every extra update helped or that whole-run CPU fell.
Unlike t9, all nine NC candidate loops stopped on CPU admission while their unit
allocations still admitted another envelope. A/N/NC residual admission was also
CPU-limited; S/H remained unit-limited. Actual shared CPU was 3.122266819 seconds.

All three shared dense base NPZ files match t8 and t9 byte-for-byte. All fifteen
selected models changed all 7288 content entries, while their decoder arrays
remained unchanged. Source/freeze/native/model/controller bindings were checked.
Actual environment metadata again shows one OpenBLAS thread and one observed
task, the same OpenBLAS0.3.30 library hash and CPU affinity0-4. Boundary records
do not resolve the historical shared-preparation slowdown.

The source verification suite passed 171 independent tests in 4.991 seconds.
Its log and the exact command, environment/source/freeze identity, timestamps
and nonzero status are retained. Root49 tests had passed before these confined
independent-kernel changes; they are not described as a new t10 root rerun.

The saved-cost audit separates the NC content gap from the routing and complete
cost terms; the negative gate is retained without changing its interpretation.
No formal test, new held-out construction, AV generation, long-interaction,
device or production qualification ran. No identical-source retry is planned.

Next implementation candidate: adaptation-only fused Adam, preserving original
gradient/norm/clipping/operation order and step inventories. It would reduce
temporary arrays and Python dispatch, not declared arithmetic. Bitwise hand
proof and complete charged compilation/setup are required before a new freeze.
No CPU saving, extra update or benefit is credited to that unrun candidate.
