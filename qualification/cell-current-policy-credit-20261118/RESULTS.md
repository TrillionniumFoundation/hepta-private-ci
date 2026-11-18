# Completed current-policy credit experiment

The preregistered two resumed fits and all 108 actual evaluation calls completed.
Verified credit improves final A success from 2/6 to 5/6 and removes three A
post-success regressions. The original advancement rule still fails because
absolute recovery count is 1 rather than 2. Research NoUpdate remains in force.
Old B is 0/6 in every arm. On the new blinded B2 panel, both updated arms finish
at 3/6; credit has no unique final-score advantage.

## Fixed models, information and work

NoUpdate is the previously trained parent `430f4051`, not the untrained base.
Both new fits resume its exact measured FP32 adapter parameters
`e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f`.
Both receive the same six A records: twelve actual current-student actions and
feedback plus six explicitly curator-selected, strictly verified corrections.
The correction is not labeled as a new student execution or independent teacher.

Each fit performs 64 updates, 103,815 input tokens, 393,216 padded positions,
16,094 language-model head positions and 192 forward/backward operations.
All-observed supervises 16,094 target positions; verified-credit supervises
9,780 while retaining zero-weight forward/backward graphs for the others.
Both use the same existing rank-4 q/v adapter, seed 1729, fresh optimizer state,
learning rate 0.0001 and 2,048-token limit. No truncation or reinitialization occurs.

| Arm | New model digest | New safetensors SHA256 |
| --- | --- | --- |
| All-observed | `0585075a5277f7e8e5a7b7ad3f42bc718f17253f1dbf6c2b03e8248cfc1c1562` | `28588cb7d84113e6a30b32ec86e511c5fff456628e7ee5a1eec371f2e76a4933` |
| Verified-credit | `785bc1cea2996e33cfe02c9c51a5a3802c931b010060369fc659b47fde4440a1` | `2b868a5b225ee2402b90ad73c2700cde0e57091458ecb379e434343b22689865` |

## Full outcomes

First, final and selected are different outcomes. Every first success still
receives the fixed second model call and verifier opportunity.

| Panel / arm | First | Final | Selected | Recoveries | Regressions |
| --- | --- | --- | --- | --- | --- |
| A_retention / NoUpdate | 3/6 | 2/6 | 5/6 | 2 | 3 |
| A_retention / all_observed | 3/6 | 2/6 | 5/6 | 2 | 3 |
| A_retention / verified_credit | 4/6 | 5/6 | 5/6 | 1 | 0 |
| B_exposed_development / NoUpdate | 0/6 | 0/6 | 0/6 | 0 | 0 |
| B_exposed_development / all_observed | 0/6 | 0/6 | 0/6 | 0 | 0 |
| B_exposed_development / verified_credit | 0/6 | 0/6 | 0/6 | 0 | 0 |
| B2_blind_future / NoUpdate | 4/6 | 2/6 | 5/6 | 1 | 3 |
| B2_blind_future / all_observed | 3/6 | 3/6 | 4/6 | 1 | 1 |
| B2_blind_future / verified_credit | 4/6 | 3/6 | 5/6 | 1 | 2 |

### A: paired task transitions

P means the original strict business verifier passes; F includes every format,
original-behavior and wrong-control failure. The arrow is first to final.

| Task | NoUpdate | All-observed | Verified-credit |
| --- | --- | --- | --- |
| A-counter | F → P | F → P | F → P |
| A-mse | F → P | F → P | P → P |
| A-readout-score | P → F | P → F | P → P |
| A-clipped-metrics | P → F | P → F | P → P |
| A-pair-map | P → F | P → F | P → P |
| A-colon-repair | F → F | F → F | F → F |

The smaller recovery count has a specific denominator cause: MSE changes from
F → P to P → P. The parent/control have three initially failed A tasks and recover
two; credit has two initially failed A tasks and recovers one. Counter still
recovers, and colon repair still fails. The common failed tasks do not lose an
observed recovery. This does not change the preregistered absolute-count gate:
the required count of at least two is not met.

The other three changed A tasks are readout-score, clipped-metrics and pair-map:
each changes P → F into P → P. Initial-success retention therefore changes from
0/3 to 4/4. These are results on exposed A experience, not an independent user
sample. A proposed follow-up with common fixed historical prefixes must use its
own prospective protocol and must not rewrite this experiment.

### B2: paired task transitions

| Task | NoUpdate | All-observed | Verified-credit |
| --- | --- | --- | --- |
| blind-b2-django-is-same-domain | F → P | F → P | F → P |
| blind-b2-django-escape-leading-slashes | F → F | F → F | P → P |
| blind-b2-pydantic-to-pascal | P → F | P → P | P → P |
| blind-b2-pydantic-to-snake | P → P | P → P | P → F |
| blind-b2-more-itertools-first-true | P → F | F → F | F → F |
| blind-b2-more-itertools-quantify | P → F | P → F | P → F |

Credit gains escape-leading-slashes but loses the second-call success on
to-snake relative to all-observed. Both updated models fix the parent's
to-pascal regression, but both lose the parent's first-call success on
first-true. Quantify still regresses in all three arms. The gains and losses
must remain visible alongside the two equal 3/6 final scores.

B2 consists of six newly authored requirements from django, pydantic and
more-itertools, with exact upstream source and license bytes. Another executor
sealed it before receiving the final model manifests, and released it only after
independently hashing both manifests and WEIGHTS_FROZEN. This is operational
separation in a shared workspace, not authenticated independent custody.
Public pretraining overlap is unknown, authenticated independent users remain
zero, and six functions do not establish broad generalization.

## Costs and complete originals

| Arm | Evaluation input tokens | Output tokens | Calls / verifier calls | Output caps | Evaluation wall window |
| --- | --- | --- | --- | --- | --- |
| NoUpdate | 15772 | 2900 | 36 / 36 | 2 | 228.912 s |
| all_observed | 15586 | 2317 | 36 / 36 | 0 | 191.141 s |
| verified_credit | 15539 | 2075 | 36 / 36 | 0 | 193.598 s |

The two internal training windows are 297.715 and 299.090 seconds. Across eight
disjoint owned child stages, measured wall time is 1431.678 seconds and
completed child CPU time is 1448.902 seconds. Generation alone totals
534.825 seconds, nested inside the evaluation stages; it must not be added again.
All 108 model calls and 108 attempt verifications are counted, including 37
format rejections and two output-cap failures. The owned stages also perform
12 training-reference and 18 evaluation-reference checks. Six earlier corpus
correction checks and the separate B2 curator's twelve reference/tautology checks
are reported separately. The parent already had one 64-step fit; its historical
cost is not duplicated for both resumed arms. Energy, currency and full system
cost remain unknown; deployment, checkpoint and concurrent system overhead
are not silently treated as zero.

`complete-originals.tar.gz` contains 586 original files plus its index, including
both exact 2,193,720-byte trained adapter tensors, all requests, raw outputs,
verifier receipts, feedback histories, training steps, freezes, source deployments,
durable job exits and exit witnesses. Previously available base-model bytes are
referenced by their pinned manifests rather than copied into this archive.

- Archive: 4511826 bytes; SHA256 `95beda262721a747aeb3180b7d7f37a245735870b3ee0c8c58e80e45857b9bb6`.
- Original index SHA256: `a97062044b5252b98ea983f7e1107741ba49697aff2055c27d21c703e903c099`.
- Complete readout SHA256: `9448a6bef0064086d3b126cb11d7ee62a0243217acbe222b7d9323214add45f9`.
- Weight freeze SHA256: `dabd5f13f8cc7392e8eb8b8eccbe1fd30dcc4da381d31a51e70818d255bc3bcd`.
- A second executor independently rechecked all 108 raw call/receipt bindings,
  published B2 records, release timing, controls and costs without new model or
  verifier calls. Its summary SHA256 is
  `afdf9eb3bd3816a815b6f63d732ce8fbc6578565f5340019b0a70a981cb9521e`.

Actual training source remains `6a7696b0c0c5a0a2ba0fb52160aabb191850b2d3`; actual evaluation source
remains `048014f8634059b65b24f49da7f00d5b1bb85737`. The later collector and evidence commits do
not relabel these executions. A local workspace outage was handled through the
durable remote originals and direct GitHub publication; no model call was replayed.
No result grants native adoption, FinalUse or settlement qualification.

## Supplemental original-output review

`MECHANISM_REVIEW.json` binds twenty original outputs/receipts to the unchanged
archive index. It documents the changed MSE input that rejects the constant
control, the three removed post-success A corruptions, the remaining colon
signature/JSON failures, and the offsetting B2 interface and semantic failures.
No answer is rescored or regenerated. `independent-audit.tar.xz` contains the
separate auditor's eleven original files, including its initial engineering
failure and corrected review; SHA256
`b89a33732d89a593ab98d3b89deff141c27c3b05583cdc8b59f29a8e92129999`.
