# Actual first-choice critic consumption

## Execution and scope

The protocol in `FROZEN_PROTOCOL.json` was fixed before outcomes from 16 fresh synthetic development sources were read. Four future draws and four arms yielded **256 actual multimodal continuations, with zero failures**. All arms used the same original generator and subsequent sampled actor. The calibrated checkpoint supplied only value heads for an external first-choice rule. Both complete model snapshots remained unchanged throughout evaluation.

For each source, a shared encoded prefix and named future tape were paired across the four arms. The planner evaluated all legal candidate actions using public state only, selected one action, and then handed execution back to the original actor. It did not repeatedly replan. Its measured CPU/wall cost reduced the successor budget and was included in the delivered return. Actual PNG/WAV/GIF/text outputs, independent readbacks, outcomes and full cost events are retained for each branch.

## Delivered returns

All values use the unchanged gamma-2 entropic CE and normalized utility/cost units. There are 64 executed outcomes per arm, clustered into 16 original sources.

| Arm | Population CE estimate | Mean delivered utility | Mean measured per-request cost | Mean planning cost |
|---|---:|---:|---:|---:|
| Original sampled actor | 0.533909 | 0.570638 | 0.017909 | 0 |
| Original critic chooses first action | 0.531505 | 0.569775 | 0.018776 | 0.000184 |
| Calibrated critic chooses first action | 0.532121 | 0.566415 | 0.015268 | 0.000204 |
| Immediate STOP | 0.531757 | 0.557024 | 0.007165 | 0 |

The value heads were actually consumed by the decision rule. Original-critic first choices were video 20, text 20, shared 12, verify 8, and STOP 4. Calibrated first choices were verify 28, STOP 20, and text 16. Since the first-choice rule is deterministic at the shared source prefix, these correspond to STOP on 1/16 versus 5/16 sources and verification on 2/16 versus 7/16. Repeated future draws are not additional independent task contexts.

## Paired source-level comparisons

Intervals below are 1,000-replicate paired percentile bootstraps over the 16 original sources. They are development uncertainty summaries, not multiplicity-adjusted confirmation.

| Comparison | CE difference | 95% interval |
|---|---:|---|
| Calibrated critic minus original critic | +0.000616 | [-0.007074, +0.008870] |
| Calibrated critic minus sampled actor | -0.001788 | [-0.015453, +0.011708] |
| Calibrated critic minus immediate STOP | +0.000364 | [-0.008266, +0.009769] |
| Sampled actor minus immediate STOP | +0.002152 | [-0.007477, +0.012371] |

Calibration changed actual choices and reduced average generation expense, but it also reduced average delivered utility. The net risk-adjusted effect is small and uncertain. **This run does not establish that the calibrated first-choice rule improves delivered NDU over the original critic, the actor, or immediate STOP.** Every registered comparison remains in `RESULT.json`; no alternate checkpoint, threshold, or source subset was selected after reading these outcomes.

## Cost interpretation

Per-request costs include the common encoded prefix, the planner when present, subsequent runtime control and generation, codecs, readback/observer work, the runtime seal, and the measured caller-close gap. The final consumer receipt write is outer study work. Common preflight identity checks and auxiliary snapshot saving are also outer study work. The reported loop measured 10.636431 CPU seconds and 17.912281 wall seconds, including the source-cluster comparison work. Cold loading and the preceding calibration training are not amortized into the table's per-request costs. These numbers therefore are not total research-lifecycle expense, production latency, or market prices.

## What is closed and what remains open

The execution gap between a fitted critic and an actual bounded generation decision is closed for this prototype: distinct value heads selected distinct first actions, real continuation consumed them, and the complete output/cost consequences were measured. The stable-benefit hypothesis remains unresolved. The rule is approximate and applies once; its suffix value refers to the original actor, avoiding an unsupported claim about a new repeatedly replanning policy.

This remains a small synthetic mechanism task, not natural multimodal semantic qualification, full general NDU semantics, production owner integration, or a proof of global optimality. All qualification flags remain false, and no reserved confirmation sources were consumed.
