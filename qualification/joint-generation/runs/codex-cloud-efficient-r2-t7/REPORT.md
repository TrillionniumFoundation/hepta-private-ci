# Preparation-forecast r2 build: stopped before candidate training

Actual exit **1**, source `2a08efc131c7bd241466cd48d1e4297e3f1be060`, execution/freeze commit `862b16d43e`.

Original error: `ValueError: shared build leaves no useful candidate training budget`.

The fixed shared build consumed 9.077421498000 process-plus-child CPU seconds and 3611371737 declared operator units. With the unchanged 10-second cap, nine candidate validations, tail and next-step guards, it left no admissible candidate training allocation. No candidates completed, no selected model or selection.json was created, and no controller fit, selected-model validation/export or formal test was run. This does not demonstrate whether the new preparation forecast would help; it was not reached.

The shared-phase telemetry records one process thread, about 7.826 seconds of parent CPU, 14.826ms total observed GC (3.188ms maximum), no major faults/OOM, and zero container CPU-throttle counter increase during the interval. These observations do not identify the slowdown's cause or establish a quota denial. The earlier shared build costs were 3.202s in t5 and 6.543s in t6. The actual cost and failure remain intact; no budget/base-model/gate was changed and no new-directory repeat was used to obtain a pass.

Completed source verification before this frozen run: 28 affected refinement/runner tests passed, exit0, 0.261s; affine integration previously passed 143 tests. The trained affine standalone smoke remains in t6 and is not reclassified as this run's qualification.

Next independent diagnostic: a single protocol-first cProfile of this same shared TRAIN/validation preparation in the selected cloud environment. It must retain fresh compilation, all actual cost, full shared metadata and profiler overhead, remain separate from qualification, and never construct the formal test. The hypothesis and first-goal evidence remain open.
