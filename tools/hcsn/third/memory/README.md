# Memory normalization: mechanism, controls and fresh development

This stage changes only files under `third/memory`. The prior `next/` model,
protocols, checkpoints and failed results remain historical evidence.

## Hypothesis and exact scope

The old cumulative update has inverse mass `r=1/(1+sum(w))`, normalized Gram
`G=r*sum(w*k*k.T)` and cross-statistic `H=r*sum(w*k*v.T)`. Consequently

```
solve(G + lambda*I, H) = solve(sum(w*k*k.T) + lambda/r*I, sum(w*k*v.T)).
```

Even orthogonal distractor writes increase the effective unnormalized ridge.
The alternative `solve(G + lambda*r*I, H)` keeps the unnormalized ridge fixed.
This removes only normalization-induced shrinkage; interfering keys, incorrect
writes, changing values and compressed-memory limitations still exist.

For fixed ridge, `condition(G+.01I)<=101` remains the prior bound. For the new
mass convention, the exact-arithmetic bound is `1+sum(w)/.01`; it grows with
write mass. There is no numerical floor, stopped mass gradient, or claim of
uniform long-time stability. `validate.py` independently checks solve adjoints
and real recurrent parameter gradients. Development records actual condition,
solve residual and read magnitude at both diagnostic lengths.

For write mass M=sum(w), query norm<=1 and coordinatewise bounded values,
the mass-convention read satisfies |read_j|<=sqrt(M)/(2*sqrt(lambda)). This
follows from max_s s/(s²+lambda)<=1/(2*sqrt(lambda)) applied to the weighted
key matrix. It is a growing bound, unlike the fixed normalized-ridge bound.
The final tanh still bounds the memory feature; it can also saturate, so this
does not provide a uniform gradient or information-retention guarantee.

The first frozen implementation actually failed its FP32 adjoint stress at
`r=1/4097`: condition327761, maximum normalized adjoint error0.007966 exceeded
the original0.005 tolerance despite residual9.6e-8. Its complete source freeze,
numeric failure and logs are retained in `revision1/`; no development data or
training had begun. Revision2 uses float64 for all sixteen-dimensional matrix
construction/solves in every branch, including fixed controls, and casts the
read back to state dtype. States and learned parameters remain float32.
It keeps the original gradient tolerances and quality/data/update protocol.
Revision2's final JSON serialization then failed on a NumPy boolean; its
source, freeze and incomplete log are separately kept in `revision2/`.
Revision3 then exposed a second scalar type, float32, at the same output step;
it is retained in `revision3/`. The current evidence writer explicitly converts
all NumPy scalar types to Python values before JSON serialization and repeats
the validation. The graph-pass log lines alone are not a completed pass.
It additionally gates `condition*solver_epsilon<=.001` and separately records
`condition*state_epsilon`. Improving solver precision does not remove rounding
in previously accumulated float32 states or prove long-time system accuracy.

## Experiments and controls

`diagnose.py` is NumPy-only. It reproduces an orthogonal-distractor example,
inspects all twenty old memory checkpoints' filler write gates, and replays
ten old FullHX/sigmoid checkpoints at lengths128/512. Both ridge reads use the
same frozen hidden/statistic trajectory. These are already-exposed old tests,
so the counterfactual cannot count as a new confirmation pass.

The new development protocol has eight branches, three new initialization/data
seeds, two tasks:48 trainings. All use600 Adam updates,batch32 and an approximate
6200-parameter target, matching the prior update budget. They share newly
generated training data and length32 validation checkpoints. Length128/512
outputs are development diagnostics, never checkpoint-selection criteria.

| Family | Risk | Call | Ridge modes |
| --- | --- | --- | --- |
| full | Compiled FullHX | Compiled FullHX | fixed,mass |
| sigmoid | sigmoid(2z) | Same compiled FullHX | fixed,mass |
| c1 | .5+.5*z*abs(z)/(1+z²) | relu(-z)²/(1+relu(-z)²) | fixed,mass |
| memory | No fast/slow dynamics | None | fixed,mass |

The new sigmoid control deliberately retains the same FullHX Call. The old v4
sigmoid used a simplified Call, and is retained unchanged in the historical
diagnostic. C1 is an explicitly nonfinancial control with zero center slope,
not a financial pricing solution. Dynamic branches have identical parameter
shapes and initial values; pure-memory widths match the parameter budget,
not state size or FLOPs.

The frozen development gate requires the full_mass candidate to pass memory128
at95% and retrieval128 at90% in every development seed, improve mean memory512
by at least2 percentage points relative to full_fixed, lose at most1 point in
retrieval512, and pass the numerical checks. Every branch and failure is kept.
Passing screens this memory mechanism for a separately frozen confirmation;
it does not prove financial-gate benefits or authorize backbone pretraining.
If this gate fails, the stage ends with the diagnosis and no retuned rerun on
the same development outcomes.

## Data and evidence boundaries

New development RNG and initialization seeds are specified in `protocol.json`.
`data.py` checks exact `(x,dt)` content against old v3/v4 matching-length
training, validation, tests and challenges, and between new development
evaluations. Repetition among finite short training sequences is permitted.
No new confirmation dataset is constructed by these scripts.

`freeze.json` records source bytes before development. `diagnostic_results.json`
records old-checkpoint counterfactuals; `numerical_validation.json` records every
gradient step size and solve stress case. `development_results.json` is resumable
only under the same source freeze and checkpoint hashes. Completed matrices
cannot be silently rerun. Each run stores weights, data fingerprints, validation
history, source/initialization hashes and timing. CPU timings are shared-host
measurements; state count and table bytes are not measured training memory.

## Commands

Run from the repository root using the project's declared CPU dependencies.
The reference environment has JAX/JAXlib0.4.38 under `/tmp/hcsn-jax-20261029`.
Choose two valid CPU IDs for the executing host; the recorded run uses2,3.

```bash
python -B tools/hcsn/third/memory/freeze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/diagnose.py
PYTHONPATH=/tmp/hcsn-jax-20261029 JAX_PLATFORM_NAME=cpu OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/validate.py
PYTHONPATH=/tmp/hcsn-jax-20261029 JAX_PLATFORM_NAME=cpu OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/development.py
```

The training runner clears JIT caches after each completed run. Its recorded
process peak RSS uses the Linux `resource` convention; these execution and
affinity measurements are explicitly Linux reference measurements.
Checkpoints and result files use fsync plus atomic replacement. Before each
training run, the original runner pauses when shared cgroup usage exceeds7.5GB. Known
interruptions preserve elapsed attempt cost and reason. An unobserved process
exit preserves its outstanding attempt and is reported with unknown cause and
unknown completed cost; it is not silently counted as a finished run.

### Recorded scheduling amendment

After the first completed training and before the second, the original admission
rule repeatedly paused on reclaimable file cache in the shared cgroup. The first
run, original pause history, source freeze, numerical receipt and log are preserved
byte for byte in `before_operational_amendment/`; `operational_handoff.json` records
the verified inter-run stop. No interrupted training needed to be repeated.

`operational_amendment.json` freezes a separately hashed `operational_driver.py`.
The driver admits the next run only when the conservative estimate
`memory.current-max(0,inactive_file-file_dirty-file_writeback)` leaves at least
1.5GB below the cgroup limit. It records raw usage, the cache components, working
set estimate and OOM counters. Only resource admission and provenance-writing
callbacks change; all frozen scientific source bytes and the passed numerical
receipt keep their original hashes. CPU affinity remains2,3. This resource
estimate is a scheduling heuristic, and timing across the restart/cache boundary
does not support a comparative performance claim.

The remaining47 trainings use this exact command; the driver resumes saved runs
and refuses to rerun a completed matrix:

```bash
PYTHONPATH=/tmp/hcsn-jax-20261029 JAX_PLATFORM_NAME=cpu OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/operational_driver.py
```

After47 completed runs, shared-memory pressure caused another admission pause.
`final_run_handoff.json` and `before_final_run_restart/` preserve that boundary.
The idle process was restarted to release retained JAX caches; the identical
driver then resumed the last run under the same1.5GB requirement. All47 prior
result rows and weights stayed unchanged. This added no training attempts and
is included separately in the elapsed-time accounting.

After the matrix completes, independently replay it without retraining:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/audit_development.py
python -B tools/hcsn/third/memory/summarize.py
```

The summarizer independently checks the development decision, complete unique
run matrix, validation-only checkpoint selection, budgets, weights and evidence
hashes. It reports descriptive per-seed results and measured costs. It is a
post-run auditor and never trains, constructs a confirmation set or selects a
candidate. Its own source hash is included in `development_summary.json`.

If a declared retrieval quality gate fails after the complete matrix and replay,
`retrieval_counterfactual.py` diagnoses the six FullHX development checkpoints
with both final read conventions at128/512. Each comparison preserves the entire
trained trajectory and all weights. Its separate exploratory plan was recorded
after32 development runs were exposed; it is explicitly a failure analysis on
seen development inputs and cannot change the decision or become confirmation.
The script refuses to run when both retrieval quality checks pass.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 2,3 python -B tools/hcsn/third/memory/retrieval_counterfactual.py
```
