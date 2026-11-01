# Typed retention: two content revisions and executed READ/STOP control

Both typed cores passed the preregistered content-retention gate on all nine nonmissing conditions. The result closes the observed-distractor overwrite failure in this declared symbolic task family. It does not establish an analytical-core advantage: the ordinary core reaches the same measured quality with lower CPU cost. Missing-target prediction remains weak, and neither these tasks nor their alias bridges constitute real multimodal foundation-model validation.

## Identity and confirmation boundaries

- Version one source: `63b348005c468e29e89f9f309d525d87661ee06b`; confirmation seed61101.
- Typed revision source: `6809dd449cecaad4f192b5bd176a11f91223769c`; 18 fresh fits; candidate manifest SHA256 `468459cd0353f7a84dd108edd5c7b416dc2beda0e972cdca87224d9e135c59a4`; new confirmation seed73117.
- Typed control source: `0ba19482533b0d714eebe4fa58b4544ca03aac6f`; train/dev117101; confirm118101; policy SHA256 `7da628a4a0c46e2656369352f8cb5b2945c0f534c0f82ba4ea80a49f2face88e`.
- The revision was explicitly informed by the first confirmation failure. Cross-version values below are descriptive because the two confirmation samples differ; within-version core contrasts retain paired episode identities. All models were fixed before their respective new confirmation.

## Content outcomes

Values are three-seed means in percent. Every fit uses 1024 confirmation episodes with four queries.

| Task | Core | V1 base query / all-four | V1 128 observed tokens query / all-four | V2 base query / all-four | V2 128 observed tokens query / all-four |
|---|---|---:|---:|---:|---:|
| mqar | flow | 99.910 / 99.642 | 13.330 / 0.098 | 100.000 / 100.000 | 100.000 / 100.000 |
| mqar | diagonal | 100.000 / 100.000 | 12.272 / 0.033 | 100.000 / 100.000 | 100.000 / 100.000 |
| selective | flow | 99.967 / 99.870 | 12.573 / 0.033 | 100.000 / 100.000 | 100.000 / 100.000 |
| selective | diagonal | 100.000 / 100.000 | 11.995 / 0.130 | 100.000 / 100.000 | 100.000 / 100.000 |
| binding | flow | 99.959 / 99.837 | 13.493 / 0.000 | 100.000 / 100.000 | 100.000 / 100.000 |
| binding | diagonal | 100.000 / 100.000 | 12.541 / 0.000 | 100.000 / 100.000 | 100.000 / 100.000 |

In V2, all162 registered nonmissing fit/condition outcomes had100% query accuracy and100% all-four correctness, including observed64/128-token interference, matching silent delays, irregular clocks, resampling and query exchange. These are not162 independent training replications: there are only three seeds per task/core and paired/reused confirmation episodes. Flow and diagonal base all-four differences are0; the95% and98.333% bootstrap intervals are[0,0] because no observed errors distinguish them. This degenerate interval does not prove population equality or zero future error.

The repair gives both cores exactly the same explicit event-type eligibility: declared WRITE may update value memory and BRIDGE may update relation memory. The learned gate remains within eligible writes. Every raw observation still reaches the encoder and physical-control computation. A same-weight DEV intervention verified identical control tensors and restored128-token all-four correctness from0 to100% in six seed17 task/core cases. This identifies irrelevant writes as the immediate failure mechanism; it is a shared semantics prior, not a benefit attributable to analytical propagation.

### Missing observations remain a separate limitation

All available queries were answered correctly in V2 missing-observation runs. The missing final target is not recoverable with certainty, but that does not make the model's guessing behavior optimal. The unavailable-query accuracy is very low, below the 12.5% accuracy of uniform guessing among eight answer classes. These measurements do not identify the precise cause of those errors. No abstention or posterior-calibration qualification is claimed.

| Task | Core | All-query accuracy % | All-four % | Available-query accuracy % | Unavailable-query accuracy % |
|---|---|---:|---:|---:|---:|
| mqar | flow | 75.090 | 0.358 | 100.000 | 0.358 |
| mqar | diagonal | 75.098 | 0.391 | 100.000 | 0.391 |
| selective | flow | 83.114 | 32.454 | 100.000 | 0.048 |
| selective | diagonal | 83.105 | 32.422 | 100.000 | 0.000 |
| binding | flow | 75.065 | 0.260 | 100.000 | 0.260 |
| binding | diagonal | 75.065 | 0.260 | 100.000 | 0.260 |

Maximum resampling logit differences: Flow1.1444092e-05; diagonal9.5367432e-06, below the fixed1e-4 tolerance.

## Executed typed READ/STOP comparison

A is typed diagonal plus the development-selected lightweight price threshold; B is the same core plus the common value controller. C and D are the corresponding typed Flow arms. Each READ obtains the actual missing final raw event and spends0.1 additional time; both complete continuations are retained. Utility is mean four-query correctness minus the quoted READ price. CPU and that symbolic price are separate accounts.

| Task | A utility | B utility | C utility | D utility | READ rate % |
|---|---:|---:|---:|---:|---:|
| mqar | 0.849472656 | 0.849472656 | 0.849554036 | 0.849554036 | 79.004 |
| selective | 0.849228516 | 0.849228516 | 0.849228516 | 0.849228516 | 79.004 |
| binding | 0.849472656 | 0.849472656 | 0.849472656 | 0.849472656 | 79.004 |

| Task | Effect | Mean utility difference | Paired95% interval | Degenerate |
|---|---|---:|---|---|
| mqar | B-A | 0.000000000 | [0.000000000, 0.000000000] | True |
| mqar | D-C | 0.000000000 | [0.000000000, 0.000000000] | True |
| mqar | C-A | 0.000081380 | [0.000000000, 0.000325521] | False |
| mqar | D-B | 0.000081380 | [0.000000000, 0.000325521] | False |
| mqar | (D-C)-(B-A) | 0.000000000 | [0.000000000, 0.000000000] | True |
| selective | B-A | 0.000000000 | [0.000000000, 0.000000000] | True |
| selective | D-C | 0.000000000 | [0.000000000, 0.000000000] | True |
| selective | C-A | 0.000000000 | [0.000000000, 0.000000000] | True |
| selective | D-B | 0.000000000 | [0.000000000, 0.000000000] | True |
| selective | (D-C)-(B-A) | 0.000000000 | [0.000000000, 0.000000000] | True |
| binding | B-A | 0.000000000 | [0.000000000, 0.000000000] | True |
| binding | D-C | 0.000000000 | [0.000000000, 0.000000000] | True |
| binding | C-A | 0.000000000 | [0.000000000, 0.000000000] | True |
| binding | D-B | 0.000000000 | [0.000000000, 0.000000000] | True |
| binding | (D-C)-(B-A) | 0.000000000 | [0.000000000, 0.000000000] | True |

The learned value controller selected the same actions as the strong lightweight price rule in every registered typed confirmation case. Consequently B-A, D-C and the interaction are exactly0 in this sample. D-B is0 for selective/binding and8.138e-5 for MQAR, whose interval includes0. No positive analytical or learned-controller increment is established. Always READ restored100% four-query accuracy but had utility0.83453125 after its price; the price-selective policies achieved approximately0.8492–0.8496. Never READ had approximately0.750–0.751 utility. A useful READ action does not establish a benefit of the more complicated controller.

## Costs and latency

Disjoint external wait4 receipts below include interpreter/import/write work. Inner per-fit and application timers are nested in these numbers and must not be added again. The phases are not equal-size portfolios: V1 includes51 fits and dynamics/legacy controls; V2 includes18 typed fits.

| Phase | Outer CPU seconds | Wall seconds |
|---|---:|---:|
| campaign001_train_meter | 714.581908 | 244.765270 |
| campaign001_confirmation_meter | 278.292731 | 283.595012 |
| control001_train_meter | 14.097558 | 15.067109 |
| control001_confirmation_meter | 17.978894 | 18.116498 |
| retention001_train_meter | 397.559356 | 208.008578 |
| retention001_confirm_meter | 155.313179 | 167.521971 |
| retention_control001_train_meter | 13.566950 | 13.640014 |
| retention_control001_confirm_meter | 16.166379 | 22.728484 |

The four typed formal phases total582.605864 CPU seconds. This excludes separately retained development diagnostics/smokes, historical acquisition, AV frontends and final packaging; it is not a complete deployment energy estimate.

For matched content fits only, the nine V1 Flow fits consumed255.572 nested fit CPU seconds versus129.806 for diagonal. The nine typed Flow fits consumed263.392 versus128.386: approximately2.052 times as much. These inner timers are diagnostic comparisons, not additional ledger totals. Parameter counts remain8314/8389; persistent state counts447/440 for Flow/diagonal.

Latency below is the mean across three seeds of each fit's nine-repeat median, in milliseconds, for the complete MQAR sequence. The reference implementation is uncompiled, single-thread CPU; it includes tensor conversion and excludes encoder/media acquisition.

| Core | Condition | Batch1 ms | Batch24 ms | Batch24 episodes/s |
|---|---|---:|---:|---:|
| flow | base | 5.725 | 8.376 | 2865.887 |
| flow | long_tokens_128 | 35.157 | 63.703 | 377.019 |
| diagonal | base | 3.012 | 3.850 | 6270.032 |
| diagonal | long_tokens_128 | 26.453 | 36.210 | 665.113 |

The ordinary typed core is faster at the matched observed quality. This statement concerns the executed dense reference implementation, not an inherent complexity theorem about all analytical models. GPU throughput, attributable joules and production Rust execution remain unmeasured here.

## Evidence

- [V1 confirmation](../campaign001/confirmation/RESULTS.json)
- [V2 complete confirmation and intervals](../retention001/confirmation/SUMMARY.json)
- [V2 paired DEV diagnostic](../retention001/diagnostic001/SUMMARY.json)
- [Typed control confirmation and intervals](confirmation/SUMMARY.json)
- [Typed policy freeze](POLICY_FREEZE.json)
- [Independent retention acceptance](../retention001/INDEPENDENT_ACCEPTANCE.json): all 18 fits and 180 condition records verified, with source/checkpoint/raw identities and regenerated inputs checked.
- [Independent typed-control review](INDEPENDENT_REVIEW.json): all 18 raw confirmation batches, 36 calibration archives, 15 source snapshots, 18 checkpoints and 15 effects verified; regenerated first-query features, labels, prices, actions and utilities agree.
