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

## Training-only implementation follow-up after t1

The first independent training/validation run exited 2 with effective-reference
CPU-net delta -0.009623; no independent test was opened. Its complete receipts
and standalone export/reload evidence were retained in commit `f8b15aea9e`.
Content updates were real, but this did not pass first-goal readiness.

The next source revision leaves the plan, objective equations, rho, CE weights,
prices, budgets and benefit gates unchanged. It removes redundant input/policy
checks from the internally generated training path while keeping public input
validation, and aggregates a ledger's existing totals once per atomic charge
rather than once per counter. Every system receives these same optimizations.
The declared inventory removes the checks that no longer execute.

A hand-random-input no-update microprobe (five repeats of 150 calls per arm,
alternating old/new order; optimizer deliberately disabled) measured median
CPU ns/call S 604615→446413, H 748867→508854, A 663407→575294,
N 791126→693288. Digests/updates were unchanged. This diagnostic excludes the
optimizer and shows timing variation; it cannot establish whole-build benefit.
Seven learning tests and 22 combined learning/accounting/freeze tests passed.
A new immutable source freeze precedes the next actual training/validation run.

## Counterbalanced diagnostics after t2

t2 also exited 2: NDU and NDU-control exceeded the unchanged CPU cap. Independent
bounded TRAIN replays exactly reproduced its abnormal saved weights in normal
millisecond steps, with finite float64 weights/Adam state and no subnormals. One
static full-service batch had also consumed 5.3236 CPU seconds. The historical
slowdown's cause remains unresolved; this is not evidence of a repaired runtime.

The next predeclared source rotates arm order across candidate, validation and
formal measurement rounds. Only each arm's active CPU is charged, with shared
scheduler CPU attributed in full to every arm. Phase/resource/GC evidence and
native-service component times are retained, and an observed overrun immediately
stops subsequent work with its partial ledger. Exception paths preserve actual
cost and original errors. The data, objectives, price, caps and benefit gates do
not change. The formal test remains unopened. Before this freeze, 92 independent
source tests passed; the final affected runner suite passed 12 tests after its
last exception-path fix. Evaluator coverage is 17 tests, not all metadata-only.
