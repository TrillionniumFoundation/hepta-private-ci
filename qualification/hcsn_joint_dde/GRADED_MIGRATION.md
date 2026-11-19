# Executable graded initial-law migration: bounded numerical result

**HOLD_NO_GO.** This candidate closes a finite, explicitly measured migration
and short-gap numerical defect on the already exposed original population.
It does not establish observation filtering, recursive posterior rollout,
full-network gradients, complete C2 training replay, independent task benefit,
or product adoption. No old result or original checkpoint was rewritten.

## Why this is a separate candidate

A backward continuation quadrature can be accurate even when the corresponding
rollout initialization is wrong near the absorbing boundary. Ordinary linear
hat weights assign some initial uniform-cell mass directly to the lower node.
The actual `JointModel.solve` correctly refuses that unrecorded initial hit.

This change uses a fixed graded mesh
`x_i = 8 * expm1(6*i/n) / expm1(6)` with 256 or 512 intervals. Its positive
birth/death rates preserve the local first and second spatial moments.
`JointModel` now reads explicit mesh nodes for its reset stencil and perpetual
closure. Uniform generators use the same node interface and retain their
existing behavior. The graded generator refuses the inherited uniform-grid
derivative routine; graded full-parameter AD is not implemented here.

Uniform cells and the exponential tail are integrated against nonnegative
linear hats. The lower hat's mass is transferred to the first interior node,
without normalization and without asserting a time-zero event. This changes
the original continuous law locally, and its bias is reported. On the first
uniform source cell, its mean shift is 3.70401e-7 at 256 intervals and
9.15182e-8 at 512 intervals. Probability and arbitrary signed content use the
same map. Original uniform remaining-time laws become exact rational-support
phase packets; new hits continue to use the actual DDE flux history.

The upper state remains permanently active and nonreturning. The initial
exponential-tail basis has 0.0407622 probability beyond the new endpoint;
its weighted contribution and approximation error must not be interpreted as
a solved returning-tail problem.

## Actual complete retained-population execution

The original hash-bound 12 arms, 384 training rows and all 14,336 retained
positions were loaded. Both original prior and posterior laws were evaluated
on all six recorded gaps: 0.001, 0.003, 0.02, 0.04, 0.08 and 0.16. All gaps are
shorter than the fixed 0.2 delay. Consequently, the exact discrete
first-excursion kernel and the original phase-release integrals describe the
same model before any newly produced hit can reenter.

For every retained position, the continuation value of the **migrated state**
was compared with the unchanged original 80-digit reference and the unchanged
1% scaled-error threshold. The supplementary noncancelling error adds the
absolute spatial/migration error and upper truncation error separately.

| Grid intervals | Original positions | Failures at original 1% | Maximum scaled continuation error | Maximum noncancelling scaled error |
|---|---:|---:|---:|---:|
| 256 | 14,336 | 0 | 1.58748787e-5 | 1.58749080e-5 |
| 512 | 14,336 | 0 | 4.00956339e-6 | 4.00959286e-6 |

The finite-gap reference uses half-line Brownian first-hit and discounted
occupation formulas integrated over the unchanged continuous source laws.
64- and 128-point reference quadratures differ by at most 1.90126e-14.

| Grid | Law | Maximum absolute M error | Maximum absolute H error | Maximum absolute A error | Maximum relative M error |
|---|---|---:|---:|---:|---:|
| 256 | Prior | 1.77841e-5 | 1.74940e-5 | 8.77189e-7 | 0.776905% |
| 256 | Posterior | 1.34908e-5 | 1.32985e-5 | 8.50528e-7 | 0.047326% |
| 512 | Prior | 4.45728e-6 | 4.38457e-6 | 2.19913e-7 | 0.194795% |
| 512 | Posterior | 3.37957e-6 | 3.33141e-6 | 2.13186e-7 | 0.011571% |

M is first-hit probability on these short gaps, H is its discounted measure,
and A is discounted active time. Relative M is defined only where the reference
is at least 1e-12; **all 14,336 prior and all 14,336 posterior values meet that
floor**, so no original visit is excluded. Smaller rare-tail probabilities are
not qualified by this result.

The complete laws use a linear kernel evaluation. They are not 28,672 separate
DDE integrations. Separately, **30 actual `JointModel.solve` executions** were
performed: the first retained posterior from every arm and three declared
boundary/tail/phase fixtures at each grid. Their full probability and signed
content arrays, initial migration receipts, query-time fields and step counts
are retained. Their maximum M/H/A disagreement with the discrete spectral
kernel is **2.09109e-11**. This checks the adapter's actual solver path without
mislabeling a backward-value calculation as a rollout.

## Source, timing, tests and limits

The exact parent is `36aa7bc7c36a56861a5ce70bc143a7dde16c5e49`. The local source
was frozen in commit `dd7c26b` before `attempt001`. The identical numerical
source was published as `b8272c7606e5bc0191a41d2d55839f9e9b62855a` while that
attempt was running; this is **not** a claim of GitHub preregistration before
execution. The mesh choice and engineering checks were informed by prior
failure/exploration on this exposed population. They are recorded openly in
`GRADED_PROTOCOL.json`, not presented as independent scientific confirmation.

The run checked all eight repository Python modules in its execution import
closure and the protocol before and after execution. All input hashes also
remained unchanged. The three extra test-only modules (`test_model.py`,
`test_graded.py`, `reference.py`) are in the separate complete Python source
hash witness in `FMT.json`. The archived source guard does not pretend those
test-only modules ran inside `audit_graded`.

**14 tests passed, zero skipped:** eight inherited joint-flow checks plus six
new checks covering uniform-grid equivalence, conservative nonproportional
signed migration, actual DDE versus spectral evaluation, boundary refinement,
multiple-reset comparison with the independent serial CTMC, and rejection of
invalid meshes/laws and unsupported gradients. The test invocations lasted
1.944s and 18.585s respectively. Required `just fmt --base 228986c` exited zero;
all numerical source and protocol bytes were unchanged. No tests were rerun
after formatting.

The complete retained-population invocation exited zero. Process-only resource
receipt: wall 111.093s, user CPU 108.403s, system CPU 2.075s, peak RSS 392,216 KiB.
The runner's internal scope measured 110.361s wall and 109.758s CPU. Python
3.12.14, NumPy 2.3.5 and SciPy 1.17.0, one BLAS/OpenMP thread. These are not full
lifecycle, training, energy or matched-baseline costs. New neural training
calls and independent future tasks are both **zero**.

## Raw evidence and replay

`evidence/graded-migration-20261112/attempt001/MANIFEST.json` identifies every
preserved file. The two NPZ files retain all per-visit IDs and metric columns.
`IDENTITIES.json.gz` and `DIRECT_DDE.json.gz` are lossless, deterministic gzip
copies; the manifest includes both compressed and original decoded hashes.
All raw stdout/stderr, process outcome and formatter records remain separate.

The original audit input summary must hash to
`12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822`.
The immutable source inputs are the original training-domain audit archive
(SHA256 `a36500c6dd8f41adff6b50aaf23910100be3fd0a4641aee07a692aa1ccc7ec35`),
including its hash-bound per-arm derived traces and audit records. The source
loader refuses an incomplete roster or changed original input bytes.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python -B -m qualification.hcsn_joint_dde.audit_graded \
  --input-root /path/to/original/run/audit \
  --output-dir /path/to/new-attempt
```

Output directories must be new. Historical failures and previous attempts
are never overwritten. The next distinct gates are continuous observation
filtering on the persistent state, multi-delay/multi-update rollout accuracy,
graded physical and content gradients, and real retraining with independently
admitted complete C2 recovery. This numerical result grants none of those gates.
