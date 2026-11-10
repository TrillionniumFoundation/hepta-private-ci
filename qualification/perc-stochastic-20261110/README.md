# PERC stochastic training and measured development run

**Engineering evidence advanced; scientific and production status remain HOLD.**
This adds actual randomly initialized SGD/momentum training rather than changing the seed label of deterministic ridge. It does not supply new independent sources.

## Executed scope

Each verification run fitted global, dense and public heads with seeds 1101, 2202 and 3303: **9 fits, 1,800 optimizer updates**. Each condition used the same 128 TRAIN and 32 DEV paired rows already retained from real earlier collection.
Global/dense features came from the previously executed/recomputed encoder;
this run made no new encoder calls and did not evaluate those neural policies.

Each fit retains its initial weights, ordered minibatch digests, per-step loss,
parameter/optimizer digests and final weights. The three seeds have distinct initialization, order and final parameters for each condition. A second provenance-hardened verification produced the same 9 parameter/order traces.
These are **three stochastic repeats per condition**, not six independent repeats
and not eighteen independent fitted models.

Only public heads were deployed to actual OCR on the known 16 DEV documents. Each run completed **96 task executions and 144 OCR observations** across three
public heads and matched direct-ROI controls. DEV calibrates the models, so these
outcomes are descriptive rather than independent evaluation.

| Seed | Public-active correct | Direct-ROI correct | Public/direct online proxy cost |
| --- | ---: | ---: | ---: |
| 1101 | 12/16 | 12/16 | 2.027803 |
| 2202 | 12/16 | 12/16 | 1.968304 |
| 3303 | 12/16 | 12/16 | 2.022523 |

Keep direct-ROI acquisition for this public-coordinate task. No positive latent
increment, complete four-arm policy evaluation or new confirmatory result is claimed.

## Cost and validation

The Linux process envelope includes command imports, startup, fitting, OCR,
evaluation and command bookkeeping in measured lifecycle wall time. It separately retains waited CPU, largest waited-process RSS, output hashes, failures, timeouts
and cancellations. Own meter import and final receipt write are excluded. Detached or unreaped descendants, commercial bills and energy are unproved; process-tree
completeness remains null. Do not sum this inclusive wall time with phase times.

The final targeted gate passed **33 tests, zero failures/skips**: stochastic heads,
existing head serialization/selection, real process outcomes and cancellation
races, source-reuse checks and rejection of a changed live extractor before OCR.
Required `just fmt` passed with all seven tested Python ASTs unchanged.

See REPORT_V1/V2, FITS, ENVELOPE_V1/V2, TRAINING_IDENTITY, FORMAT, VALIDATION and
PRIVATE_EVIDENCE JSON files. Raw known TRAIN/DEV, private heads and both original
attempts remain in the private archive. No confirmation payload was opened.

## Remaining acceptance

Fresh semantic tasks without answer coordinates, all four protocol families,
independent source/template groups, matched strong baselines and complete paid-cost utility remain open. Production source permission, reservation ownership, ordinary daemon capture, restart reconciliation and next-task use also remain open. Existing source-reuse protection and all original scientific thresholds stay in force.
