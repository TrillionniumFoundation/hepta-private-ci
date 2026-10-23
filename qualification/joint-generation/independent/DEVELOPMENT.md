# Pre-freeze development evidence

These checks are implementation diagnostics. They are not held-out acceptance
results and did not construct the independent formal test fold.

- The original r1 narrow gates passed, but padded training/routing comparisons
  did not establish net benefit against effective static generation. Its 98
  retained files remain sealed and unchanged. The r1 dynamic policy's mean raw
  utility gain over always-full was about 0.002345; pricing its additional full
  forwards at the unchanged 0.02 gives about -0.005627 before critic cost.
- A hand-generated random-array native microprobe (1000 requests, hidden 32,
  excluding PNG/JSON) was negative: full versus low-plus-critic CPU was about
  0.0410/0.0691 seconds without the ledger, and 0.2374/0.2910 with it. Compilation
  was about 0.2394 seconds. This motivated useful batch execution; these numbers
  are not a batch-service performance claim or a model experiment.
- The first native batch test run exited 1. An all-full random route without a
  folded thumbnail encoder raised `FloatingPointError: native batch kernel
  returned 1`. C validation incorrectly required the unused low encoder. The
  fix validates only the path actually executed, without preparing a useless
  encoder to satisfy the check. The final native suite passed ten tests.
- Independent review of protocol commit `4577537660d2889960dcf1f891127dc73d681925`
  found that the first 64 training rows covered only one source scene. Before
  source freezing, calibration changed to deterministic training-only bipartite
  matching. The actual training metadata yielded 72 unique physical sources,
  six rows per source class and six per target class. Selected input identity:
  `39ad109caf5b5f94d4f7d590993738698bb989330294247bfdb4da6c52d024ed`.
- The same review clarified that one-pass random-view quality does not isolate
  routing causality: continuation has an extra information opportunity. The
  narrower comparison label is explicit. The primary effective-baseline gate
  still requires positive complete CPU-net utility including amortized build.
- Before full source freeze, 67 independent source tests passed (2.055 seconds,
  exit 0). They cover objective equivalence, actual updates, no-padding useful
  work, native batch parity, source/budget guards and opening-marker refusal.
  The existing root/media suite had already passed 40 tests. None of these
  results is substituted for the new formal benefit gates.

Only the fixed-rho finite text/image prototype is in experimental scope. Typed
audio/video envelopes preserve timing and capability boundaries; this backend
explicitly declines their generation. Synchronous AV, long interactions,
device measurements and production qualification remain future work.
