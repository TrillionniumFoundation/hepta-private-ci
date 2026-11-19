# Completed layout experiment: NoUpdate

The prospectively designated native-feedback candidate did not meet its promotion rule. Both A and B3 failed the required strict final-score improvement over P. All original model calls completed and all original strict failures are retained; successful owner exits do not represent successful repairs.

## Fixed sequence and identities

Both actual models were trained from the same cold P parameter state, with fresh empty AdamW, 32 updates each, full 3584-position inputs and the unchanged 70% CUDA cap. Native feedback was fixed as the primary arm before B3 evaluation; document evidence was the matched-information control. Execution source remains `78099aa6af4c70c00f26cb11888e20aa59510014`, with execution files identical to `02b3fb49ac00ccb7ad28e5d803af5675fbd28e26`.

The actual weight freeze at `1795035781626593132` ns preceded the independently checked B3 release at `1795052080045352852` ns. B3 materials were separately prepared and withheld until the two real weights were frozen. Release commit is `928dcad44d049ae0b229f0b5bbe37d0f23de1f96`. This operational separation does not establish authenticated independent custody or exclude base-model pretraining contamination.

The original cap of 56 new generations was completed exactly: A 24 and B3 32. Eight original A P generations were reused, yielding 64 audited rows. No training, A model call, B3 model call or verifier run was repeated to obtain this readout.

## Strict task outcomes

| Panel | Arm | First | Final | Any attempt | Common P prefix | Recovered / opportunities |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A | P | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| A | document_evidence | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| A | native_feedback | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| B3 | P | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| B3 | document_evidence | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| B3 | native_feedback | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

All 56 new outputs failed the original patch-admission gate, so zero native test children executed. The first/final/any columns remain distinct metrics even though all are zero here. There were no successful first attempts or parent second attempts to preserve, making those preservation checks vacuous. Empty lost-success sets are not evidence of preserving an existing capability. Native common-prefix success did not strictly contain document success on either panel.

This is the unchanged research decision **NoUpdate**. The numerical training and engineering gates did not demonstrate task-level gain, real adoption or settlement eligibility.

## Actual generation cost

| Panel and arm | New calls | Input tokens | Output tokens | Output-cap hits |
| --- | ---: | ---: | ---: | ---: |
| A document evidence | 12 | 26,338 | 17,551 | 7 |
| A native feedback | 12 | 25,844 | 17,618 | 8 |
| B3 P | 8 | 10,627 | 1,563 | 0 |
| B3 document evidence | 12 | 21,345 | 14,029 | 5 |
| B3 native feedback | 12 | 20,525 | 16,311 | 4 |
| Total | 56 | 104,679 | 67,072 | 24 |

Every call retained the common 8192-input/2048-output caps and complete input. Actual token and wall costs differed. Equal caps do not make realized costs equal, and this experiment does not close E1's full frozen/retrieval/answer-SFT/trajectory-SFT cost comparison.

## Failed and completed model-phase costs

`COST_LEDGER.json` checks original wait receipts and sampled counter identities across 15 measured stages and ten nonoverlapping whole-host windows:

| Measured stage group | Stages | Owner stage wall, seconds | Child CPU, seconds |
| --- | ---: | ---: | ---: |
| Preparation, including all original OOM and rejected calibration work | 7 | 331.360 | 331.467 |
| Two actual fits and final weight audit | 3 | 1329.922 | 1349.036 |
| A evaluation | 2 | 2536.121 | 2570.271 |
| B3 evaluation | 3 | 2436.301 | 2486.828 |
| Measured subtotal | 15 | 6,633.705 | 6,737.602 |

This includes four actual OOM/wiring failures, the numerically rejected SDPA attempt, the successful short-A engine check, the successful full-length gate, both real fits and the full evaluation. Zero optimizer updates in a failed attempt do not mean zero computation. Original partial-forward/backward traces and detailed inner-checkpoint counters remain retained.

Internal training/generation timers are nested inside these stage windows and are not added again. Sampled CPU-package counters total 362,409.545 joules across the ten nonoverlapping windows. They include concurrent host activity, assume no multiple counter wraps between samples, and are not model-only energy. Earlier parent training/source acquisition, controller/API/network activity, unmeasured engineering/archival work and idle gaps are outside this subtotal. GPU energy, network energy and monetary cost remain unknown; complete system cost is not claimed.

## Original evidence and diagnosis

`ACTUAL_EVALUATION.tar.xz` is the complete 202,240-byte evaluation archive, SHA `3b852f7dc5917ea9b338db9dc6d7619562285496f70bef3bc48a00c2254030b1`. Its 1,350 members contain 4,188,870 uncompressed bytes and were individually checked against `INDEX.json`, SHA `4611b651e50ff0734fcd15a0973e4816d6485d16db05016712f381ed34ba06a3`. It includes actual requests, raw outputs/token IDs, strict verifier and feedback receipts, owner waits/energy samples, original reused P calls, frozen source and model identities, released B3 bindings, the A-only diagnostic, and cost originals. Both actual adapters and full fit receipts are separately published in `../training/ACTUAL_TRAINING.tar.xz`. The full upstream B3 source/test material remains bound to the original release in PR #6720.

`READOUT.json` SHA is `d122f4e32f75a53e06238dd1260a676f8542a9f0dc3aee6e15eb15521d05063a`; `COST_LEDGER.json` SHA is `b2b05e61e3545dcbab553f73b72b03d1f8e3ec312b819942b0eb533732aec0b2`. Readout, cost accounting and archive verification added no model or verifier calls.

The A-only audit in `../A-mechanism/` confirmed actual token/target/causal alignment and fresh optimizer state, while identifying repeated escaped strings, invalid edit structures and literal old-text mismatches. No specific implementation mismatch was found in those checked paths. A future shared replacement-function interface is a new engineering candidate requiring its own strict CPU controls and protocol; it cannot change these original scores.

Authenticated users remain zero. These public historical maintenance materials do not establish user-growth curves, multi-teacher complementarity, native adoption, or complete reward/cost eligibility. All earlier NoUpdate decisions remain intact.
