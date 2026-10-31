# Independent pre-confirmation review

Status: **the identified completeness and failure-receipt defects were corrected
and independently re-reviewed at the revision hashes below.** No confirmation or
research-audit outcomes were generated or inspected for this review. Actual
result review remains required; source-level checks do not establish efficacy.

## Reviewed source identity

The following initial versions were read in full. Their findings are retained
below as the review history, rather than erased after correction.

| File | SHA256 |
| --- | --- |
| `statistics.py` | `c093fcb0ccd934cf1674b09451274db109485720dad0fcb381b3cb3bce177586` |
| `profile.py` | `e37e62818fa7c46fac1ed3121755ee13c12768874d9c277e1ea27ed8286ba9c8` |
| `study.py` | `b7366a6b02927c934be1f60bd3b9102e5241a0f070f2e2db8a0f5909f28fa39b` |

Targeted timing and utility fields in `policy.py`, `learning.py`, and the draft
`PROTOCOL.json` were also inspected to interpret these files. This is an
implementation/statistical review, not a new independent paper referee report.

### Independently re-reviewed revision

| File | SHA256 |
| --- | --- |
| `statistics.py` | `6c9e0bce1d6259c32f8c54019fe88327ef64db6201d91fd698b79773462afd0b` |
| `study.py` | `3c9146d360245b0fe639f0f0fcbad55f0e01cdaa20bc6ad4016adc776856c40b` |
| `profile.py` (unchanged) | `e37e62818fa7c46fac1ed3121755ee13c12768874d9c277e1ea27ed8286ba9c8` |
| `test_statistics.py` | `83d1b0a95ecb7da64b5ae125b58b30b2d47b767c176f9c79cb1af98be95d02c5` |
| `test_study.py` | `d41ca588170c2cb9ac4edb2d1f39f56a37262c4912dfb7938a3eee082b9d786c` |
| `evidence/REGISTERED_CHECKPOINTS.json` | `0e22689b17efd7d0e4069d3bfea0239879feb3d7c318eb40ee2619d1c2b39125` |

All seven statistics/runner tests were executed independently and passed. A
separate synthetic complete identity family with 295 placeholder rows also
passed the positive gate at one episode per arm/fit. These are software checks,
not reduced-size confirmation or efficacy observations. Confirmation internal
streams use 920,000,000 plus the registered regime/fit/episode offsets; the
development namespace is separate.

The final checkpoint-selection correction was also reviewed and tested. Each
registered `(model, ablation)` now maps to one explicit directory; the corrected
temperature control can only load from `fits_temperature_corrected`. A retained
legacy file is rejected even when the corrected file is absent. The statistics
training table enumerates exactly 12 registered model/ablation pairs times five
seeds, instead of globbing possibly duplicated legacy checkpoints. The added
rejection/substitution test passed, and all 60 registered paths and actual file
SHA256 values were independently checked against `REGISTERED_CHECKPOINTS.json`.
The identity-grid, bootstrap, primary contrasts and cost-scope logic were
unchanged by this correction. Inclusive batch-cost receipts intentionally still
include the retained unsuccessful/superseded attempts.

## Checks that passed at the reviewed versions

- The runner pairs arms on the same external fixture and internal random stream
  within each fit/episode. Different fits have disjoint confirmation fixture
  namespaces. Arm execution order is randomized for timing fairness.
- The reported bootstrap resamples fit clusters, then whole paired trajectories
  within each selected fit. It does not treat timesteps, events, or neural draws
  as independent fitted models. Its scope is conditional on shared train/dev
  data. Five fits remain a weak estimate of retraining uncertainty.
- Three primary contrasts use the predeclared Bonferroni adjustment. The
  seed-level t interval is separately reported as a sensitivity analysis.
- `registered_return` and measured process CPU time are distinct quantities.
  The former uses declared decision/event utility coefficients; it is not an
  energy, currency, or measured CPU-price result.
- The runner explicitly states that task DP is optimal for original task
  utility only, and is not an optimal bound on the additional registered neural
  compute/event objective.
- Component profiling is a separate warm microbenchmark and is not added to
  inclusive rollout timers. The direct control explicitly bypasses the core;
  its otherwise unused kernel benchmark is marked illustrative.
- Original Gaussian endpoint, finite CTMC first-passage, sampled policy,
  continuous-limit accuracy, native integration, and production claims remain
  separate in the surrounding contracts.

## Finding C1, corrected: observed identities cannot define the expected sample

At the reviewed hash, `matrix()` infers episode IDs from surviving rows and only
checks five fits times the *observed* episode count. Common omissions across
fits therefore shrink the sample silently. Arms with equally many but different
episode IDs can be subtracted by position, violating the paired estimand.
Entire registered arms not used in an explicit contrast can disappear from the
summary without a completeness error.

A synthetic, non-confirmation reproduction was executed:

```text
Fit IDs: 11..15
A episode IDs: [0,1], value = episode ID
B episode IDs: [1,2], value = episode ID
matrix() accepts both as shape (5,2), despite registered N=512
Reported positional B-A mean: +1
Actual B-A on the only common episode, 1: 0
```

Required correction: validate the exact frozen Cartesian identity set before
any contrast: registered regimes/arms, fitted seeds, and all expected episode
IDs. Validate fixture/internal-seed pairing and the run receipt's status,
counts, record digest, and frozen-manifest identity. Any missing, duplicate,
failed, unexpected, or nonfinite required row must produce an incomplete
report, with no affirmative primary gate. Do not redefine the estimand using
survivors. The re-reviewed `validate_identity_grid()` now enforces the complete
26-arm nominal and 11-arm-per-stress identity family for fits 11--15, validates
fixture/internal seeds and receipt counts, and runs before any contrast.
`summarize()` also checks frozen-manifest and raw-record digests. Incomplete
families produce an incomplete summary with no contrasts or affirmative gates.
The reproduced common-index/absent-arm problem and wrong future streams are
covered by passing tests. C1 is closed at the re-reviewed hashes.

## Corrected failure boundary and retained reporting limits

**F1 — Incomplete execution receipts.** At the reviewed runner version,
serialization with `allow_nan=False` occurs outside the per-trajectory try
block. A nonfinite returned metric can abort without a failed row or final
receipt. The revision moves serialization into the per-trajectory try block and
retains outer-abort receipts with completed counts and incurred time. Injected
missing-checkpoint and nonfinite-result failures both left incomplete receipts,
with the latter retaining all six failed development rows. F1 is closed for
these tested failures; an unavailable filesystem cannot itself guarantee that
an error receipt can be written.

**R1 — Amortization coverage.** Per-fit metadata starts after model/optimizer
initialization and ends before checkpoint serialization. The fit-plus-online
CPU table is therefore a component estimate, not a complete delivered-cost
estimate. Inclusive training-run receipts capture additional work. Disclose
both scopes without adding overlapping timers. `fits*` does not automatically
cover development, legacy failed runs, validation, or the historical build;
an all-cost claim needs an explicit coverage/exclusion ledger. The revision
labels the amortization table partial, lists covered batch configurations,
retains inclusive batch totals, and explicitly identifies early-smoke gaps and
historical-build exclusions. This resolves the misleading-coverage risk, not
the absence of measurements that were never recorded.

**R2 — Standalone resource semantics.** Retain decision/event proxy costs as
separate summary fields, and label `wire_bytes` as encoded packet bytes unless
actual transport was measured. The broker separately measures real JSONL UTF-8
request/response bytes. The profiling `categorical_draw` benchmark measures a
CDF/search operation on a fixed mass and fixed variate, not the complete
deployed random-number generation/sampling path. Microbenchmark quantiles are
not whole-task latency quantiles. The revision adds both proxy-cost columns and
serialized-versus-transport semantics to SUMMARY. It also adds matched-deployment
secondary comparisons `D - continuous_hard` and `D_mean - continuous`; the
original `D - continuous` changes both law and deployment and remains descriptive.

## Limits and result review still required

The frozen nominal test uses balanced public-parameter presets. The registered
pooled within-fit bootstrap also varies preset composition; it should be
described as uncertainty for the declared mixture, not a theorem of exact
conditional coverage for fixed stratum counts. This does not change the
predeclared procedure after seeing outcomes.

After freezing and execution, review the actual identity counts, failures,
per-fit primary contrasts, interval multiplicity, proxy-versus-CPU tables,
conditional Qpi phases/calibration, snapshot receipts and native scope. A
finite simulator improvement does not establish superiority on raw document
understanding, open-domain Hepta tasks, continuous QVI, optimized hardware,
production Rust neurons, or energy use. Conversely, a negative cell result
must remain a result rather than trigger favorable-seed or comparator changes.
