# Pocket4 full-encoder and recorded-metric audit

## Decision

The complete installed Laya CPU/F32 path passes this bounded engineering probe.
It does not qualify a forecasting, trading or weight-editing improvement. The
previous scale-1000 head-only tolerance failure remains failed. The frozen
Hepta terminal-anchored experiment also remains a negative efficacy result.

This package records new work on November 5, 2026. Its synthetic probe,
recorded-metric audit and current service snapshot are separate observations
with separate clocks and contracts; they are not one atomic live snapshot.
Prior research is in `../wsp_native_value_20261105/` and
`../wsp_followup_20261105/`. No production checkpoint or admission setting was
changed. Existing training services remained running.

## What was actually on Pocket4

`current/public_snapshot.json` finished at 05:12:09 UTC / 00:12:09 America/New_York.
The trainer's underlying status was from 05:12:00 UTC. It reported 114 completed,
two failed, zero running and zero admitted jobs. Forty-three completed candidates
had no forward trial; this is not a performance rejection. The latest candidate
was awaiting forward admission because the original source freshness,
continuity and source-quality guards were not satisfied. The configured source
TTL was 5,000 ms. No new original live quote was collected by this audit.

The trainer and evaluator services were active with zero restarts. The separate
execution service was in auto-restart with 4,122 restarts. That is an observed
operational issue, not a diagnosed weight defect or a repaired incident.

| Bound item | Identity or size |
| --- | --- |
| Candidate | `8fe51f354c8a75001b0948c3588cab7d62dcb54c90f932f32e7bf9eb1505bf5a` |
| Base revision | `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67` |
| Base weight SHA256 | `9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204` |
| Base weight bytes | 643,835,514 |
| Actual pretrained parameters | 321,908,995 |
| Candidate adapter SHA256 | `94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0` |
| Adapter | 9,988 bytes, six finite F32 tensors, 2,379 parameters |
| Parent adapter SHA256 | `52adec4b889f2898d554877e3534f3121503f88850920868e9adc5b6547a7a73` |

The six tensors augment three targets: scorer.1 (rank two), scorer.3 (rank one),
and act_head.2 (rank one). The effective changed matrix-coordinate count in the
bound training receipt is 3,968; it is not the number of trainable factors or
the full model size. This production model is not the small 85-input / 48-tanh
research network. Its ACT/ESCALATE supervision concerns correctness of the
frozen parent's answer; it does not establish financial Call/Put or trade
authorization semantics.

Completed jobs are bounded episodes from a configured parent. Optimizer state
persists within an episode and resets between jobs; 114 completed jobs cannot
be interpreted as 114 cumulative epochs of one continuously updated model.

## Complete-path synthetic probe

The executed files are `probe_full_encoder.py`, `supervise_full_encoder.py`
and the unchanged earlier `head_probe_helpers.py`. Independent source review
and pre-execution fixes are retained in `PREEXEC_REVIEW_FULL_ENCODER.json`.
The exact executed driver SHA256 is
`f4246efa5baf5dfdbd5fc21e1638f49f1af4038fd3b7644d41d8591e0d37d5ae`.

Four explicit, unlabeled synthetic quote states cover EUR.USD and BTC.USD,
300/900-second horizons, and short/long flat, rising, alternating and falling
histories. The original pinned encoder input builder uses max_len 1024. Actual
token lengths were 388, 410, 968 and 958. These are engineering fixtures,
not private training rows or held-out forecast samples.

Each state runs parent, candidate and restored-parent factors through the
complete original model. Hooks capture the actual encoder output and the three
target heads' inputs and outputs. A separate F64 head calculation checks the
observed head inputs at the original fixed `atol=rtol=2e-5`; the encoder itself
is executed, not replaced with synthetic activations.
The rule is `abs(error) <= 2e-5 + 2e-5 * abs(reference)`; the maximum absolute
error was 1.3030747504672036e-4, which passes its corresponding relative bound.

| Check | Observed result |
| --- | --- |
| Full encoder-to-head executions | 12 of 12 |
| Independent head comparisons | 36 of 36 pass |
| Largest error / allowed error | 0.027054485156926746 |
| Encoder bytes across parent/child/restored | Equal for all four fixtures |
| Restored final outputs | Byte-identical to parent for all four fixtures |
| Complete factor identities | Match at every phase and final restoration |
| Frozen base parameters and live binding | Unchanged |
| GPU initialized, training, broker queries, orders | None |

The parent manifest has scorer adapters only. Source-initialized action A with
zero B preserves the original action-head function; an unrecorded historical
parent action A is not reconstructed. Candidate logits differ from the parent,
but the four argmax price/action outputs do not. Unlabeled synthetic outputs
provide no evidence about which forecast is correct.

The earlier scale-1000 scorer.1 gate failed at five coordinates for both parent
and candidate. The complete-path probe does not overwrite that result, widen
its tolerance, or certify a cause for it. Its observed scorer.1 input magnitudes
were approximately three, while action-head inputs reached 1,042.67.
CPU/F32 agreement here does not qualify GPU/BF16 arithmetic or all inputs.

## Recorded training metrics

`metric_audit/RESULTS.json` reaggregates stored raw probability receipts using
the same 32 row identities and labels for parent and candidate. Row identities
and probabilities stay on Pocket4; only aggregates and content bindings are
exported. This audit uses no Torch, model forward, training or evaluator job.
Labels were read from the bound receipts and were not independently checked
against the source dataset. Stored F32 softmax probabilities are scored in F64;
the original CE used F32 cross_entropy on logits. Maximum disagreement with
reported CE/Brier is 7.41e-8, below the predeclared 1e-6 tolerance.

| Same 32 TRAIN rows | Mean NLL | Multiclass Brier |
| --- | ---: | ---: |
| Parent raw, independently reaggregated | 2.3527060285 | 0.9836789713 |
| Candidate raw, independently reaggregated | 2.3504294451 | 0.9829790931 |
| Uniform seven-class analytic baseline | 1.9459101491 | 0.8571428571 |
| Recorded calibrated candidate | 1.6834371929 | 0.7949825827 |
| Recorded training-prior baseline | 1.6838880218 | 0.7950361604 |

The calibrated and prior rows are existing manifest aggregates; this audit did
not recompute them. The independently reaggregated raw candidate improves only
0.0022765834 NLL and 0.0006998783 Brier over its parent and remains worse than
uniform. The recorded calibrated advantage over training prior is only
0.0004508289 NLL and 0.0000535777 Brier on the fitting data. The v3 calibrator is
`prior + a * (raw - mean_raw)`, with a=0.0397510467570488, not a simple
96%-prior/4%-raw mixture. Source identities are bound in the metric record.
None of these results establishes future forecasting or net task value.

## Compute, failed attempts and reproducibility

`full_encoder/SUPERVISOR_RECEIPT.json` measures the complete child, including
imports, loading, forward execution, restoration and result writes:

| Resource | Measurement or enforced bound |
| --- | ---: |
| Complete child CPU | 32.746145 seconds |
| Enclosed elapsed wall (supervisor interval) | 65.710592535 seconds |
| Complete child peak RSS | 2,770,612,224 bytes |
| Actual cgroup CPU | 50,000 / 100,000 microseconds |
| Actual cgroup memory limit | 3,221,225,472 bytes |
| Actual cgroup pids limit | 32 |
| Child CPU soft/hard limits | 180 / 190 seconds |
| Child wall / enclosing runtime limits | 420 / 450 seconds |

Nested worker CPU/wall measurements must not be added to these complete-child
totals. The metric audit separately records 0.018782631 CPU seconds and
0.191957224 wall seconds for its timed body. These figures exclude agent
reasoning, dispatch, network waits and prior training. Energy was not measured.
No end-to-end training speedup is inferred.

The initial source-transfer request exceeded the shell tool's 64 KiB boundary
and was rejected before execution. `LAUNCH_ATTEMPT_1_REJECTED.json` retains that
failure. Gzip transport then delivered the independently reviewed final bytes
under a new idempotency key. The successful durable job is
`1a1aa2aa697-fc05-3e8b`; its terminal status is retained. No budget was silently
widened, and there was no second model run after the successful probe.

All checks require the actual pinned private deployment, manifests, base file
and adapters. Those source files, training rows and raw logs are intentionally
not copied into this research package. Replaying on a different installation
is a new probe that must bind new source/checkpoint identities, rather than
claiming reproduction from these public aggregate records alone.

## Evidence map

- `current/`: time-stamped sanitized service/model snapshot and capture receipt.
- `full_encoder/`: frozen protocol, full result, complete-child cost and durable
  terminal status; independent record review is distinct from a fresh model run.
- `metric_audit/`: bounded recorded-probability audit and source identities.
- `runtime_audit/`: exact #94 source/CI/build and certificate-record review.
- `literature/`: newly checked primary-source literature and scope distinctions.
- `RESEARCH_DECISIONS.md`: current diagnosis, native subsystem boundaries and
  the next scientifically valid comparison.

The overall decision remains HOLD for model efficacy and production admission.
