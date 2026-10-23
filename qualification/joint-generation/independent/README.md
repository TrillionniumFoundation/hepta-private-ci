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
revision therefore rotates systems across candidate and selected-validation
rounds, attributes only each system's active CPU, retains phase/resource/GC
telemetry, and stops further work as soon as a phase reveals an actual CPU
overrun. This changes scheduling and observability; the data, content objectives,
prices, complete budget caps and benefit gates remain unchanged.
