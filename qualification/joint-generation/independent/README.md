# Independent efficient-budget qualification

`plan.json` declares new comparisons before any independent test construction.
Its scope is fixed synthetic text and learned RGB, using the same 32-unit shared
encoder and two categorical heads. The r1 source and retained run are immutable.

The systems are full CE, same-weight 0.2 CE, additive utility, fixed-rho entropic
utility, and entropic utility with a learned continuation controller. Only the
applied objective is computed. Fixed-decoder outcome kernels are cached once and
each content update reuses one encoder pass. Static systems do not fit or execute
an unused critic; their saved budget admits additional useful updates.

Both build limits apply to every complete system: 12 billion declared operator
units and 10 process-CPU seconds. Every system is attributed the full shared data,
decoder/base training, validation/calibration and native compilation cost. Search,
all candidate validation, controller targets/fitting and necessary model exports
also consume budget. Declared units price bounded mathematical kernels; actual
CPU also includes interpreter, copying, compiler, model serialization and runtime
bookkeeping. They are not equal hardware FLOPs, latency or energy measurements.
Final administrative result-receipt writing is recorded separately from model
build work rather than called generation or silently used for padding.

Source instances add independently sampled brightness, background and vertical
offset. All eight instructions and two sensor variants of one physical source
stay in a single split. Default train/validation/test contain 192/72/72 physical
sources and 3072/1152/1152 rows. The semantic vocabulary remains twelve familiar
scene classes. No r1 checkpoint is reused: the common base is newly trained on
the new training fold only. Merely importing data or a protocol does not create
the test, and `dataset('test', profile)` rejects by default.

The common native runtime supports a true 58-dimensional thumbnail encoder,
mathematically equivalent to the original upsampled thumbnail. Fixed batches of
up to 64 requests include actual validation, routing, generation, output PNG/JSON
and accounting CPU. Batch latency is retained; this is not an individual-request
latency qualification. CPU confidence intervals cluster fixed service cohorts,
while raw content confidence intervals cluster physical sources.

Validation fixes each efficient static mode and the efficient reference system.
Runtime calibration uses a deterministic training-only matching: 72 distinct
physical sources, six per source class and six per target class, interleaved
across all twelve classes. It does not use the class-ordered first training rows.
The controller is compared with that reference using CPU-priced utility,
including the complete build cost amortized over 100000 requests per selected
seed. Raw joint success, quality retention, operator-priced utility and isolated
controller comparisons remain visible. A failed gate cannot be replaced by an
improvement on a different metric.

The no-critic random single-view comparison is a cheaper quality baseline. It
does not isolate adaptation from the controller's extra continuation opportunity;
the primary system claim rests on the complete CPU-net effective-baseline gate.

The optional input-only router has structural/unit coverage but is not searched
or qualified by this protocol. Its cost is not concealed inside r2 or charged to
static baselines.

After all source bytes have been committed, freeze an immutable receipt, commit
and push that receipt, then train/select. The evaluator is a separate action:

```bash
python -m independent.run freeze --receipt independent/frozen-r2.json
python -m independent.run train --freeze independent/frozen-r2.json --out runs/codex-cloud-efficient-r2-t1
python -m independent.run evaluate --run runs/codex-cloud-efficient-r2-t1
```

The last command is authorized only after validation readiness and frozen-source
checks pass. A nonzero train status retains its receipt and leaves the test shut.
The fixed `independent/efficient-r2-test-opened.json` marker prevents a repeat in
another output directory. Original r1 results are never reopened or retuned.

Run source tests without creating any independent test data:

```bash
python -W error -m unittest discover -s independent -p 'test_*.py' -v
```

`independent.serve.export_bundle(run, system, seed, out)` copies the exact
selected model, optional critic and hashed native library into a standalone
bundle. `load_bundle` and `infer` reload that bundle and accept the existing typed
media envelope without labels or observers. The request binds the exported
bundle digest and retains actual PNG, caption, budget receipt and checkpoint.
This single-request smoke does not qualify the frozen batch-throughput profile;
an export from an unready training run does not imply experimental acceptance.

The retained t1 and t2 training/validation builds failed readiness; neither opened
the independent test. t2 also exceeded CPU limits and showed a seconds-long
static full-service batch. Exact bounded training replays reproduced its weights
in milliseconds, leaving the historical slowdown unexplained. The next protocol
revision therefore rotates systems across candidate, selected-validation and
formal measurement rounds, attributes only each system's active CPU, retains phase/resource/GC
telemetry, and stops further work as soon as a phase reveals an actual CPU
overrun. This changes scheduling and observability; the data, content objectives,
prices, complete budget caps and benefit gates remain unchanged.

The balanced t3 build also failed readiness: content and NDU validation gains
were positive, but control CPU-net utility against the selected NDU/full
reference was -0.004409. All actual build caps held; no independent test opened.
These are validation diagnostics, not evidence of qualified benefit.

The next prospective revision aligns the critic with raw decoded task utility.
Its routing threshold is `0.02 * cost_ratio`; the global complete-system price
remains 0.02. Each selected control model measures complete service on the fixed
72 training calibration inputs under forced stop and continue, retaining both
paths' low/critic work and actual sampled caption, PNG, JSON and ledger costs.
Three paired repeats alternate AB/BA by repeat and seed index, using the same
sample seed within each pair. The median per-request incremental CPU, clamped
below at zero, is divided by the frozen full-service reference CPU. This is a
training-only local marginal estimate, not a guarantee of external net gain.
Mandatory controller/output and all calibration costs remain in total budgets.

All five systems may also spend affordable residual budget on the selected
models, retaining their original Adam and RNG states. Complete seed rounds
rotate system/seed order, with no new LR/mode selection or validation stopping.
Exact future operator inventories and training-only CPU forecasts reserve
critic, paired calibration, selected service, changed-model validation and
exports. An unaffordable round is skipped; an actual cap overrun still fails.
The frozen plan records forecast factors and inputs, including conservative
arithmetic CPU scaling, rather than treating predictions as executed charges.
No content objective, data split, price, cap or benefit gate changes.

New standalone bundles use `native-bundle.v2` to bind the separate routing
threshold, cost ratio and full training-calibration receipt to model and input
hashes. Loading an archived v1 bundle preserves its original rule and explicitly
reports that it has no calibrated controller cost.

The next fixed controller candidate is an affine raw-gain head over the already
computed thumbnail hidden state and the original ten instruction coordinates.
A protocol-first, physical-source grouped TRAIN diagnostic supported this
smaller representation repair; no nonlinear head or threshold search was chosen.
Its complete normalization, ridge fit, paired calibration and inference are
charged. Low state is reused from the same encoder evaluation, while static
systems execute no gain head. Existing ridge artifacts remain loadable. This
implementation is not acceptance evidence; all frozen content and dynamic gates
still apply to the next actual build.

The affine t6 build retained positive validation content/NDU and control/random
contrasts, but failed the complete CPU-net control/static gate (-0.014405).
The subsequent preparation-forecast t7 build exited 1 before any candidate:
shared preparation consumed 9.077421498 CPU seconds, leaving no admissible
training allocation under the unchanged cap. Neither result opened the test.
A single separate diagnostic reproduced the same base model bytes in 4.002
shared CPU seconds; it did not explain or replace t7's failure. Its raw profile
is retained in `runs/codex-cloud-efficient-r2-shared-profile-d1/`.

Incremental accounting totals are being checked as a local implementation
optimization. The initial hand-built benchmark saved ledger CPU but its full
256-update median was 2.76% slower. That negative result is retained; neither a
microbenchmark nor positive training/validation contrasts establish independent
first-goal acceptance. The r2 formal fold remains unconstructed and unopened.

The subsequent frozen ledger-cache t8 build exited 1: complete shared CPU
12.274880402 seconds exceeded the unchanged 10-second cap before any candidate
completed. Full shared receipts are retained. The corrected one-thread,
seven-stage diagnostic had mixed update timings (4.12% median paired saving,
0.15% aggregate saving); it did not predict or establish whole-build benefit.
No identical-source repeat or formal evaluation followed this failure.

A predeclared two-pair launch diagnostic subsequently retained all four fresh
shared executions and actual NumPy/BLAS/threadpool identities. All model/library
bytes matched t8; shared CPU was 2.1–2.6 seconds and did not reproduce its
slowdown. This did not establish a fix or replace the failure. The next source
revision instead removes identified discarded Adam allocations and repeated
local decoder observations, reuses one TRAIN reward index tensor, and records
same-process numerical metadata inside charged shared CPU. Actual deleted
observer work is removed from both charges and forecasts. Original gates,
budgets, data, equations and output behavior remain authoritative.

After the unit-limited t9 failure, the next adaptation-only kernel folds exact
2x2 low-view replicas into 58 encoder features and pulls their gradients back
to the original 202-dimensional parameters. Shared dense base training remains
unchanged. Actual mask work is charged; a conservative envelope only admits an
update before its original RNG draws. Forecasts use actual ledger increments.
See [the kernel contract](TRAINING_KERNEL.md) for the fixed numerical checks and
floating-order boundary. The original benefit gates still apply; this
implementation alone does not prove that additional updates improve content.
