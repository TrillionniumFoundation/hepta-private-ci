# TRAIN certificate: the original continuation budget cannot reproduce J's required ordering

This is a separate diagnostic of the frozen [own-law Bellman study](../ndu_policy/README.md).
It does not change that study's 111 files or the 93-file native replay package.
It creates no candidate model, new held-out sample or task-value qualification.

**For each of the five original fits, an independently verified exact certificate
shows that the original continuation parameter ball cannot simultaneously satisfy
the selected zero-margin TRAIN action-ordering conditions required by J.** The
certificate also survives a conservative relaxation for binary64 dot-product
error under the stated floating-point semantics. This rules out exact copying
of those J continuation choices within that representation and budget; it does
not rule out useful partial repairs, a different beneficial policy, a larger
budget or a representation change.

## What was frozen and reconstructed

The diagnostic protocol SHA256 is
`3d5a657a7f79a5edf1e98365256b898152e384ade4031231e24f03f8f9ecdfd5`.
It binds all eight Python sources, the prior scientific protocol, exact C model
files, original archived model/data files, and the old H/Y/W and J-table identities.
The protocol and source were frozen before any diagnostic forward or numerical
witness search. The eight hand-constructed arithmetic/guard checks used no
checkpoint data. This was a local freeze, not external preregistration.

The producer reconstructed all **144,397 original TRAIN full-state rows** and
all **320 original TRAIN J tables**. Each fit's complete H/Y/W byte hashes and
every J table SHA matched the previously frozen records exactly. No seed,
training world, feature, teacher target or acceptance tolerance was changed.

Only rows where J actually chooses WAIT, READ or REPAIR are used in the
continuation system, and only against the other legal continuation when one
exists. There are **21,634 such necessary comparisons**, with 147 continuation
parameters per fit. The four-output head's Belief and terminal comparisons are
omitted, giving a weaker necessary condition. An infeasible weaker system
excludes complete matching of those continuation choices even if Belief is
edited, but a feasible weaker system would not establish full J realizability.

All original full-state rows are retained for reconstruction, including
off-policy states and distinct sunk-charge aliases. This is not a claim that
every certified row is visited by the deployed candidate or that each is
important for expected task value.

## Exact results

| Fit | Original full rows | Necessary comparisons | Nonzero witness rows | F64-relaxed squared separation ratio | Exact result |
| --- | ---: | ---: | ---: | ---: | --- |
| 11 | 28,596 | 4,450 | 4,437 | 1.623934655 | Infeasible |
| 23 | 28,417 | 4,435 | 4,427 | 1.563266534 | Infeasible |
| 37 | 28,433 | 4,161 | 4,146 | 1.353668319 | Infeasible |
| 53 | 29,215 | 3,910 | 3,776 | 1.692281479 | Infeasible |
| 71 | 29,736 | 4,678 | 4,672 | 2.028127523 | Infeasible |

The displayed ratio is the approximate presentation of the exact comparison
`d^2 / (R^2 ||A^T y||^2)`. The actual acceptance requires positive d and a
strict rational inequality above one; the rounded display is not the proof.
All five pass both the ideal-real and the more permissive F64 necessary system.

Let C be the incumbent continuation coefficients and `delta` their change.
The original declared group budget is `R^2 = sum(C_ij^2)/4`, evaluated using
the exact dyadic values of stored C. A necessary comparison forms a row A with
`+h` in the chosen continuation block and `-h` in its competitor block. The
ideal condition is `A delta >= -A C`. For any nonnegative multiplier y,
Cauchy-Schwarz makes the following a sufficient infeasibility certificate:

```text
d = y^T b > 0
d^2 > R^2 ||A^T y||^2
```

Both sides are computed exactly with `Fraction`. The numerical search need
only supply a valid nonnegative y; it does not establish the certificate.
For the F64 result, b is further relaxed by a uniform bound on both compared
dot-product errors over the entire parameter ball. The formula, no-overflow
guard, exact radius and strict-tie relaxation are documented in [MATH.md](MATH.md).

The F64 result is conditional on binary64 round-to-nearest, gradual underflow,
separately rounded products and an ordinary 49-term sum. Environment probes
record the observed process; they do not certify arbitrary hardware. The
scope does not extend to a different F32 path or to edits of the hidden
representation.

### All numerical search limits are retained

Each fit ran its one predeclared nonnegative L-BFGS-B search and reached the
**3,000-iteration limit**. All five records have `solver_success=false` and
status 1. None is presented as a converged minimum-distance solution or an
exact smallest required radius. The final best witness still satisfies the
independent exact separation test. There were no restarts, margin changes,
fit replacements or additional solver searches.

The search took 27.159575619 CPU seconds in total, nested within the producer's
cost below. It differentiates a small numerical dual objective; it is not a
claim of an entirely gradient-free diagnostic. It performs no neural-weight
training and saves no candidate model.

### The alias and analytic feasibility checks remain negative

A separate, prespecified check looked for identical hidden bytes **and** an
identical complete legal mask, within one fit, with different J first-max
actions. None was found in any of the five fits. The exact feature/mask class
counts are 24,293; 24,184; 24,032; 26,425; and 25,152. Thus repeated features
exist, but this diagnostic found no conflicting-label exact alias. It does
not establish that the representation is sufficient or that no approximate
alias exists.

The exact common-row construction also failed to fit inside the declared
Frobenius ball for all five fits. Therefore no search was skipped on that
ground. Setting all continuation scores equal would satisfy the weak
ordering relaxation, but that construction cannot be assumed feasible just
because each coordinate could fit in a separate box. It also would not
reproduce first-max READ or REPAIR decisions.

## Independent acceptance

The independent verifier uses a separately written rational accumulation,
radius/error-bound calculation and positive squared inequality. It does not
call the producer's certificate function or trust the optimizer status.

It also reexecutes **all 21,458 saved nonzero-dual witness states** against the
frozen deployed feature and checkpoint-own-law program. These witnesses span
all 320 original TRAIN worlds. Every witness hidden vector matches byte for
byte, every regenerated own-law J table matches its old SHA, and every target
matches the masked first maximum. All five fits pass.

The verifier checks the complete H/Y/W reconstruction hashes against the
frozen records, but it does not regenerate all 144,397 hidden rows a second
time: only saved witness features are independently reexecuted. This boundary
is explicit in its result. Zero exact-alias conflicts means there are no
alias double-row witnesses to reexecute in this run.

The complete summaries are [producer RESULTS](execution_r1/run/producer/RESULTS.json)
and [independent verifier RESULTS](execution_r1/run/verifier/RESULTS.json), with
SHA256 identities respectively:

```text
109aaf6c85ae65e92daf47fc118208fca0f2ce3eaec80e1e2cf28028ec9e9d5d
6e6b4fb68147a5d326edb987cb979c45554dfa6701ccd237412a5274da2fc08f
```

Every exact fraction, nonzero multiplier, witness hidden/state/teacher row,
search trace, limit termination and reconstruction receipt is retained.
Large records are deterministic gzip streams split into 479,000-byte pieces;
`io_helpers.read` checks and reconstructs the `.parts.json` manifests.

## Data and qualification boundaries

No new validation or TEST file from the own-law study is opened, generated or
scored, and no held-out row is used as a diagnostic target or selection input.
The old archived `fit_data.json` container is read in full and contains other
partitions; the diagnostic selects only its original TRAIN rows. The reused
legacy loader also initializes frozen truth-law definitions. The diagnostic
removes those attributes from its context and never queries them; that is not
a claim of memory zeroization or that no unused object can remain in Python
function globals. J targets use only the checkpoint's own stored law.

This result locates an obstruction in **the fixed representation plus the
declared continuation budget**, independent of whether MSE is solved by the
direct method or PGD. Another optimizer cannot make this same necessary
system feasible. That statement does not prove that no in-budget edit can
improve task value: a useful approximation may deliberately disagree with J
on some full-state rows, including rows it never visits. It also does not
identify a unique defective parameter or prove that the radius is the only
obstruction outside the tested ball.

The prior held-out result remains unchanged: J's structural execution passed
the finite-task gates; direct and gradient head compilation did not. This
diagnostic supplies no additional efficacy sample, global full-network
optimum, Trader benefit, production authorization or economic net-value
qualification.

## Complete execution cost

| Process scope | CPU seconds | Wall seconds | Memory observation |
| --- | ---: | ---: | --- |
| Complete producer worker | 283.641938 | 283.880070 | 272,777,216 bytes peak RSS |
| Complete independent verifier worker | 138.205378 | 138.477749 | 100,007,936 bytes peak RSS |
| Entire pipeline and waited descendants | **422.017378** | **422.568302** | 272,777,216 bytes maximum descendant RSS |

The outer row includes both preceding worker rows plus pipeline startup and
final writes. They must not be added to it again. The pipeline exited zero;
the 900 CPU-second and 1,200 wall-second resource caps were not reached. The
five numerical searches did reach their separate fixed iteration caps, as
reported above.

[The outer receipt](execution_r1/PROCESS_RECEIPT.json) includes complete worker
imports, startup, record writes and exit. It excludes the measurement
supervisor's own startup/publication, source editing, the tiny preflight and
freeze commands, input acquisition, tool transport and LLM work. Those
unmeasured costs are not called zero. This is not an end-to-end project,
training, energy or monetary-cost estimate.

## Reproduce or inspect

Use a checkout containing the stacked `wsp_20261104` package and the exact
sibling `ndu_policy` package. Recover the original public model/data inputs
using its fixed archive acquisition entry point:

```bash
python ../../wsp_20261104/joint/acquire_inputs.py --output recovered_inputs
```

For offline recovery, the acquisition helper also accepts `--repository` with
a checkout containing the pinned original archive commit. All outputs must
be new directories. Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0 were observed
in this run. Linux/POSIX process and address-space resource limits are used.

From this directory, a full reproduction of the frozen diagnostic and its
independent verification is:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -B measure_pipeline.py \
    --science ../ndu_policy \
    --joint ../../wsp_20261104/joint \
    --inputs recovered_inputs \
    --protocol PROTOCOL_FROZEN.json \
    --output independent_execution
```

To independently verify the included witness records and reexecute only
their source features/own-law tables:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -B verify_records.py \
    --science ../ndu_policy \
    --joint ../../wsp_20261104/joint \
    --inputs recovered_inputs \
    --protocol PROTOCOL_FROZEN.json \
    --run execution_r1/run/producer \
    --output independent_verification
```

Do not rerun the preparatory freeze script in the published directory or
overwrite the published protocol, toy receipt or original evidence. A
reproduction can report different numerical search timing or witness
multipliers. Its exact proof and source-identity acceptance must still pass;
the retained original witnesses can be verified without rerunning the search.
