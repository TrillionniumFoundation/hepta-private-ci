# Original170: the earlier33 cost records have been recovered

The earlier33 raw cost records are now recovered and independently verified.
Combined with the existing six-record increment, this establishes the recorded
attempt history and available cost metadata for the **39 completed keys in the
2026-11-07 23:42:37 UTC snapshot**. It does not represent new training, a new live
progress measurement, or completion of the registered170-run campaign.

This is a later addendum to the dated disclosure in PR #5331. That disclosure's
six-record scope remains unchanged. The audit belongs to the original campaign;
it supplies no completion credit to a regenerative candidate or the NDU study.

## Evidence recovered

- 33 original index files,33 start records and33 terminal records:99 newly
  recovered exact files, checked against native full-file size and SHA-256.
- Six complete bounded directory inventories cover those33 registered keys.
  All discovered attempt metadata was included. The existing six-key inventory
  and18 prior exact files were checked again.
- Across these39 selected keys, the complete metadata histories contain39
  attempts, each with a start and terminal record and its registered400 steps.
  No additional attempt, orphan terminal or unterminated attempt appeared in
  these selected histories. This statement is limited to these39 directories.
- The independent reviewer recomputed registered receipt keys, provenance,
  budget units and aggregate arithmetic from the raw files without executing
  the recovery author's reconciliation program.

| Recorded quantity | Recovered33 | Previous6 | Combined39 |
|---|---:|---:|---:|
| Attempts | 33 | 6 | 39 |
| Training steps | 13,200 | 2,400 | 15,600 |
| Training examples | 844,800 | 153,600 | 998,400 |
| Training tokens | 54,067,200 | 9,830,400 | 63,897,600 |
| Training including validation,seconds | 97,870.048485 | 31,650.226680 | 129,520.275164 |
| Sum of observed attempt spans,seconds | 107,140.452910 | 34,671.821142 | 141,812.274052 |
| Attempts with missing energy readings | 33 | 6 | 39 |

Training including validation is nested within the attempt spans; these two
rows must not be added. The overall first-start to last-terminal UTC interval is
141,813.505623 seconds, including1.231571 seconds of observed inter-attempt gaps.
Those gaps are differences between timestamps, not separately instrumented
cost components.

## Observed model-level costs in this selected snapshot

All39 records below are from the original delayed-recall portion of the frozen
campaign. Inference measurements use batch64 and100 repeats per run. The p50
and p95 columns show ranges of each run's recorded quantile, not pooled
quantiles. No p99 value is available in these records.

| Model | Completed keys | Parameters | Training+validation seconds,total | Per-run p50 range,ms | Per-run p95 range,ms |
|---|---:|---:|---:|---:|---:|
| `hx_attention` | 4 | 72577 | 21,226.762 | 4,070.61–4,219.91 | 4,777.71–6,201.19 |
| `hx_call` | 5 | 5633 | 25,787.930 | 3,906.51–4,279.81 | 4,078.13–5,842.95 |
| `hx_dual` | 5 | 5633 | 26,001.586 | 3,986.84–4,183.30 | 4,390.07–5,741.46 |
| `hx_fixed` | 5 | 5633 | 26,130.243 | 3,837.42–4,196.36 | 4,490.08–5,563.74 |
| `hx_risk` | 5 | 5633 | 1,239.938 | 198.81–209.38 | 201.20–212.35 |
| `no_recovery` | 5 | 5633 | 26,215.537 | 4,003.33–4,292.70 | 4,541.79–5,490.90 |
| `no_rollover` | 5 | 5633 | 2,095.877 | 298.73–348.45 | 306.56–429.59 |
| `softplus` | 5 | 5633 | 822.403 | 139.60–147.95 | 145.98–183.60 |

The original protocol matches hidden width. It does not match parameter count:
the attention arm here has72,577 parameters and the other displayed arms have
5,633. The JSON also retains declared trainable counts, throughput, and the
PyTorch allocator's peak allocated/reserved byte observations with their exact
measurement scope. Allocator measurements do not establish total device or
deployment memory cost. The original attention nondeterminism warning remains
in the retained historical log.

## Remaining cost and completion limits

All39 energy counter maps are missing, despite synchronized interval flags.
Full physical energy and monetary cost remain **unknown**. They are not filled
with zeros or replaced by TDP estimates.

The historical B full-shape exit-1/OOM result remains preserved under its
original SHA-256
`30b72b62cbd462109bdd7179fd22ad855f8e537f78799235d7fc1b6e103a11a1`.
It belongs to a separate stage and is outside these39-key cost sums. The absence
of another failure in these selected histories does not establish that other
keys or stages had no failures.

The selected sums also exclude earlier search and construction, other
qualification stages, native supervision, shared-device attribution, unrelated
idle time, and unmeasured storage costs. Checkpoint paths and SHA declarations
were checked against metadata; checkpoint content was not opened or rehashed.
Consequently this is not a complete experiment-cost or deployment-cost total.

The39/170 progress value remains the original dated snapshot and its global
qualification remains open. Full campaign completion and registered task
quality analysis still require the frozen workload and final reconciliation.

## Provenance and review

The full private reconciliation is115,209 bytes, SHA-256
`8ce9e05b2e0f916182f6442a83b26f0ccb27890c0bd23c6a22b68f72908fa107`.
The independent actual review is9,841 bytes, SHA-256
`840271811ec702a38a01fafd41634184512edd614ae5391b9626358f24076c5a`.
The reviewer authored the prior six-record audit, but did not operate the new33
reads or author their reconciler; this is a byte/accounting cross-check, not
blind independence from all upstream artifacts.

One initial12-file read returned generic `INVALID_ARGUMENT`; the same API and
the same paths succeeded as two six-file reads. That refusal is retained and
its precise cause is unknown. It is not counted as a training failure.

`COST39_RECOVERY_20261108.json` provides all39 public cost rows, aggregate
scopes, anonymous raw-file commitments, unknown values and review limits.
