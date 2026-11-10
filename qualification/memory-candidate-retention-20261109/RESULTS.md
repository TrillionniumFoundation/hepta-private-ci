# MEM candidate retention: real frozen-actor results

Date: 2026-11-09. Scientific acceptance: **HOLD**. Production adoption: **false**.

## Finding

The bounded pool made the correct candidate available in nine additional paired
decisions, but it did not improve correct selection or final task delivery in
this panel. Both arms achieved **11/54 unconditional successes (20.37%)**. All
54 paired outcomes tied: zero wins, zero losses and zero unknown pairs. Ten of
each arm's eleven successes were already correct at the initial handoff and
completed without `WRITE_TEXT`. Among the 44 initially incorrect cases per arm,
only one became a successful final delivery, in the same pair in both arms.[^report]

This is evidence that same-image candidate retention can repair an observed
availability gap. It does not establish a terminal task benefit, a selector
improvement, or an advantage of neural associative memory. No weights were
fitted or updated for this experiment.[^run]

## Execution and preserved preflight failure

The actor integration, independent attribution report and frozen runner are
documented in [code PR #5534](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5534).
The executed source commit was
`a4068996433f87f756455e97fe06ca1992aa63fb`.

The original `run-001` failed in exclusion metadata validation before PLAN
construction or actor dispatch. A valid sealed quarantine source was absent
from the released catalog; the original subset check incorrectly rejected it.
The correction retained the complete quarantine exclusion set and the same
registry identity without reading sealed references. The original request,
source, logs and failed receipts remain preserved in
[the preflight observation](observations/preflight-attempt-001.json).

`run-002` is explicitly a **preflight-correction**, linked to `run-001` and job
`1a1c0432b6c-5e21-992`. Its bootstrap verified the original failed receipt,
absence of an old PLAN, and empty old runner journal. The selection salt, task
design, frozen model and data bindings were preserved. This correction is not
an independent experimental or training repeat.[^bootstrap]

The frozen design contains 54 case pairs from 14 source groups: ten development
groups contribute five task families each, and four retention-validation groups
contribute one text/image-complementary case each. Each case runs once in each
arm, giving 108 planned actor episodes. Both modes use the same immutable image,
OCR, encoder, actor weights, controller, action space, 128-entry cap and
524,288-byte serialized candidate cap. Only retention between observations
changes. There is one frozen checkpoint, zero new fits and zero independent
training repeats.[^request][^run]

## Complete denominators and primary outcome

| Measure | current_only | bounded |
| --- | ---: | ---: |
| Planned episodes | 54 | 54 |
| Completed terminal episodes | 54 | 54 |
| VERIFIED evidence rows | 54 | 54 |
| UNKNOWN / REJECTED evidence rows | 0 / 0 | 0 / 0 |
| Reported timeouts | 0 | 0 |
| Unconditional successful delivery | 11/54 (20.37%) | 11/54 (20.37%) |
| Initial-correct, no-WRITE successes | 10 | 10 |
| Successful delivery from an initially incorrect state | 1/44 (2.27%) | 1/44 (2.27%) |
| Correct candidate selected at attribution anchor | 2 | 2 |
| Candidate-mediated successful delivery | 1 | 1 |
| Successful bypass of the candidate-mediated path | 0 | 0 |
| Episodes containing WRITE_TEXT | 34 | 34 |

These counts were independently recomputed from all 108 report episode rows and
matched the report panels and run attempt roster. `Completed` describes terminal
execution, not task correctness.[^report][^run]

The prespecified paired contrast, `bounded - current_only` unconditional success,
is **0 percentage points**. Its observed outcomes are 54 ties, zero wins and zero
losses. The report's missing-outcome bounds are `[0, 0]` because all final
outcomes are known; these are not a sampling confidence interval or evidence of
population equivalence. The 54 case pairs are not 54 independent source groups
or model-training repeats.[^report]

## Candidate chain and its unknowns

The anchor is the last `WRITE_TEXT` decision, or the final actor decision when
no text was written. O means a correct candidate was observed in raw outputs by
that anchor. C means a correct candidate was actually offered at the anchor.
S means the recorded selected index identifies a correct offered candidate.
D means that candidate was actually written and the complete final delivery
independently passed the existing rubric. D is a **text-candidate-mediated**
outcome; final image criteria remain part of the delivery rubric.[^report]

Every arm has 20 no-WRITE episodes whose final anchor does not process a candidate
roster. C and S are therefore unknown there, even though the episode evidence
is VERIFIED. For O, 13 of those episodes have an earlier positive observation;
the remaining seven retain O as unknown. No missing artifact or rejected
episode is silently dropped from the denominator.[^report]

| Event count, all 54 planned per arm | current_only: true / false / unknown | bounded: true / false / unknown |
| --- | ---: | ---: |
| O: raw correct candidate observed | 36 / 11 / 7 | 36 / 11 / 7 |
| C: correct candidate offered at anchor | 14 / 20 / 20 | 23 / 11 / 20 |
| S: correct offered candidate selected | 2 / 32 / 20 | 2 / 32 / 20 |
| D: candidate-mediated correct delivery | 1 / 53 / 0 | 1 / 53 / 0 |

The next table reproduces the report's conservative unknown-outcome bounds.
Every O/C/S/D-chain probability in this table has `value: null` and
`status: UNKNOWN`; none is a fully identified all-planned rate. For a conditional
row, the displayed denominator is the number with a known-true conditioning
event. Unknown conditions remain additional possible denominator members.
The bounds are not confidence intervals and need not be tight.[^report]

| Quantity | current_only: positive / known denominator | bounded: positive / known denominator | Unknowns per arm | Report bounds: current_only | Report bounds: bounded |
| --- | ---: | ---: | --- | ---: | ---: |
| P(O) | 36 / 54 | 36 / 54 | 7 O outcomes | 66.67%–79.63% | 66.67%–79.63% |
| P(C) | 14 / 54 | 23 / 54 | 20 C outcomes | 25.93%–62.96% | 42.59%–79.63% |
| P(C given O) | 14 / 36 | 23 / 36 | 7 O conditions; 13 C outcomes within known O | 32.56%–79.07% | 53.49%–100.00% |
| P(S given C) | 2 / 14 | 2 / 23 | 20 C conditions | 5.88%–64.71% | 4.65%–51.16% |
| P(D given S) | 1 / 2 | 1 / 2 | 20 S conditions | 4.55%–95.45% | 4.55%–95.45% |

### Observed decision subset: where availability changed

Both arms have the same 34 pairs with known C/S at the actual text-writing
anchor. In this descriptive execution subset, correct-candidate availability
is **14/34 (41.18%)** for current_only and **23/34 (67.65%)** for bounded.
There are nine `false -> true` availability transitions, no `true -> false`
transitions, fourteen `true -> true` pairs and eleven `false -> false` pairs.
The remaining twenty pairs have C unknown in both arms.[^report]

Among the 23 processed decisions with O true, C is true in 14/23 current_only
decisions and 23/23 bounded decisions. Correct selection is still two in both
arms; successful candidate-mediated delivery is still one. All nine newly
available correct candidates remain unselected. Thus the observed bottleneck
moves from candidate availability to selection in those pairs.[^report]

The descriptive fractions `2/14` and `2/23` among observed C-positive decisions
must not be interpreted as evidence that the selector became worse: bounded
adds nine cases to that conditioning set. They are neither a fixed-support
selector comparison nor a replacement for the all-planned primary outcome.

## Initial-delivery strata

The strata agree pair by pair between arms. They were specified before the run
and do not replace the full denominator.[^report]

| Initial stratum, each arm | Episodes | Unconditional success | WRITE_TEXT episodes | C/S unknown | O true / false / unknown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correct | 10 | 10/10 | 0 | 10 | 7 / 0 / 3 |
| Incorrect | 44 | 1/44 | 34 | 10 | 29 / 11 / 4 |
| Unknown | 0 | null | 0 | 0 | 0 / 0 / 0 |

In the initial-correct stratum, every success is explicitly classified as
`initial_no_op_success`. P(O) has bounds 70%–100%; the remaining chain
probabilities have bounds 0%–100% and null point values. There are no observed
C-positive or S-positive anchors in that stratum. These ten successes do not
demonstrate that candidate memory produced an answer.[^report]

For the initially incorrect stratum, the report gives the following counts and
bounds; all five chain point estimates remain null/UNKNOWN.[^report]

| Quantity, initially incorrect | current_only: positive / known denominator | bounded: positive / known denominator | Unknowns per arm | Bounds: current_only | Bounds: bounded |
| --- | ---: | ---: | --- | ---: | ---: |
| P(O) | 29 / 44 | 29 / 44 | 4 O outcomes | 65.91%–75.00% | 65.91%–75.00% |
| P(C) | 14 / 44 | 23 / 44 | 10 C outcomes | 31.82%–54.55% | 52.27%–75.00% |
| P(C given O) | 14 / 29 | 23 / 29 | 4 O conditions; 6 C outcomes within known O | 42.42%–72.73% | 69.70%–100.00% |
| P(S given C) | 2 / 14 | 2 / 23 | 10 C conditions | 8.33%–50.00% | 6.06%–36.36% |
| P(D given S) | 1 / 2 | 1 / 2 | 10 S conditions | 8.33%–91.67% | 8.33%–91.67% |

The initial-unknown stratum is empty in both arms. Its probability values and
bounds are null with `ZERO_DENOMINATOR`, not zero success rates.

## Failure attribution

| Report attribution | current_only | bounded |
| --- | ---: | ---: |
| Initial-correct no-op success | 10 | 10 |
| No correct candidate observed at a processed anchor | 11 | 11 |
| Earlier observed correct candidate unavailable at decision | 9 | 0 |
| Correct candidate available, incorrect selection | 12 | 21 |
| Correct selection, unsuccessful final delivery | 1 | 1 |
| Candidate-mediated success | 1 | 1 |
| Unknown stage at a no-WRITE final anchor | 10 | 10 |
| **Total** | **54** | **54** |

All nine changes in stage attribution are exactly
`candidate_unavailable_at_decision -> selection_error`; no paired final outcome
changes. The first label describes the actual offered roster, not proven
physical eviction from a pool.[^report]

The ten unknown-stage episodes per arm are initially incorrect, no-WRITE
episodes. Six have a correct candidate observed and offered earlier; four do
not have a positive raw observation. Their unprocessed final anchor does not
justify a claim that memory evicted a candidate. Together with the ten
initial-correct no-op successes, these account for all twenty C/S unknowns.
`failure_stage: unknown` and unknown chain events are distinct from evidence
status: all 108 evidence rows are VERIFIED.[^report]

The one delivery failure per arm selected and wrote the correct text candidate,
but the complete independent final rubric failed. A later
[bound receipt and geometry readback](delivery-readback/README.md) identifies the
same image-crop coverage failure in both arms: 88.8022%, below the frozen 95%
requirement. Text, preservation, original-pixel verification and the 0.5 IoU
threshold passed. This post-hoc attribution changes no original score or result.

## Observed costs and remaining scope

`run-002` recorded **93.791119 s wall** and **171.762103 s CPU**, with at most two
workers. The correction bootstrap envelope recorded **94.096478 s wall**.
The preserved failed preflight recorded 0.011600 s runner wall and 0.009702 s CPU;
its bootstrap envelope was 0.122955 s wall. Runner, episode and bootstrap
envelopes overlap and must not be added as independent costs. Energy and
provider charges remain unknown. The report has `full_cost_adjusted: false`;
these measurements do not establish a cost-adjusted advantage.[^run][^bootstrap]

Before/after weights SHA-256 is identical:
`313743619c25f7449c30982d5f2dcc96e574a9bc41730eb5c9551fb568fb57ac`.
The run records unchanged source pins and no training. The finite panel uses
fourteen source groups and one checkpoint; it provides no sampling-confidence,
independent training-repeat or sealed-confirmation result.[^run]

The intervention remains bounded candidate retention within one immutable image.
It does not test cross-screenshot/document/task memory, a learned associative
matrix, replay scheduling or continuous version transitions. Initial no-op
successes, unprocessed anchors, the changing support of conditional rates and
full delivery criteria all materially limit interpretation. Hash consistency
and the independent scoring path are not native-owner/provider authentication;
the report explicitly retains `provider_authenticity_verified: false` and
`confirmatory_use: false`.[^report]

The supported decision is to retain **HOLD**: candidate retention has a measured
availability effect in this panel, while an improvement in completed tasks has
not been demonstrated. No post-run tuning or additional actor execution is part
of this result.

## Evidence identities

The [metadata evidence archive](observations/metadata-evidence.tar.xz) is
1,355,380 bytes, SHA-256
`d3646f54f595a1dbb1d15465708a995c575fcefeb3ca857478ef55ac942b9330`.
It preserves 2,453 original metadata files plus three generated summary/index
files. [Export receipt](observations/export-receipt.json),
[local verification](observations/archive-verification.json) and the unchanged
[machine-readable summary](observations/summary.json) accompany it. Every
original metadata member was reopened and checked for size and SHA-256.

The asset index lists 3,675 original files in total. The remaining 1,222 image,
binary and source files retain their paths, sizes and hashes but their original
bytes are not included in this metadata archive. Independent pixel rescoring
still requires the bound original run images and material/reference assets.
This export is an audit-metadata archive, not a fully portable pixel corpus.

The separate [validation archive](observations/validation-evidence.tar.xz) and
[manifest](observations/validation-manifest.json) preserve available original
test, tested-source, formatting and launch-preparation records. Their inventory
distinguishes saved logs from earlier stdout that was not saved separately;
packaging does not constitute new tests or actor runs.

The original terminal evidence remains under
`/home/qq/mem-candidate-retention-20261109-a6b21bc7/`.

| Evidence | Relative original path | SHA-256 |
| --- | --- | --- |
| Independent report | `run-002/REPORT.json` | `465334e5483e263af09e68d232d08047507841c49a84e7154466b3527f12f8e3` |
| Run receipt | `run-002/RUN_RECEIPT.json` | `020ead824388c3ef994d72f65befd8479d8fe7369922171158e7aa7c514688c3` |
| Correction bootstrap | `BOOTSTRAP_RECEIPT-v2.json` | `637a12b42e865e0688be83075f4dd5c297264ec7472f789a9cd07ad597e2d316` |
| Frozen plan, as bound by both report and run | `run-002/PLAN.json` | `488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5` |
| Evidence manifest, as bound by report | `run-002/EVIDENCE.json` | `eb2c4b21fd2c91005af23c61e9a8e2ffd992817815763b25ad693587eb3de009` |
| Preserved failed preflight receipt | `run-001/RUN_RECEIPT.json` | `bda871d1df0fb78398b445265c68f047790396629f208d32ba08e117d201255c` |

[^report]: `run-002/REPORT.json`, exact SHA-256 in the evidence table. All arm, stratum, attribution and paired counts above were recomputed from its 108 episode rows; this result interpretation did not rerun the actor or alter its scoring rules.
[^run]: `run-002/RUN_RECEIPT.json`, exact SHA-256 in the evidence table. Its attempt roster has the same 108 operation IDs as the report. Original preflight costs are retained in [preflight-attempt-001.json](observations/preflight-attempt-001.json).
[^bootstrap]: `BOOTSTRAP_RECEIPT-v2.json`, exact SHA-256 in the evidence table. It records the original preflight receipt SHA, absent PLAN, empty journal, correction relationship and zero new fits/repeats.
[^request]: The executed `request-v2.json` has SHA-256 `2ad28975785858d77780e8b7c333154282916ff330c09b2f3d4aa211a8812f98`, as bound by the correction bootstrap. It preserves the original selection salt, model/data configuration and source-group design.

