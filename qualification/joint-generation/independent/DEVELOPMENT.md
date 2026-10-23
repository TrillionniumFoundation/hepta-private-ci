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

## Prospective cost-aligned controller after t3

The rotated t3 build exited 2 without CPU overruns. Validation additive-anchor
utility was +0.021224 and NDU-additive +0.006639; control versus the selected
NDU/full reference remained CPU-net negative at -0.004409. Its selected models
also received fewer content updates, and routing lost raw utility against the
same model's full view. These observations identify training/validation method
work; they do not authorize test reuse or a changed acceptance gate.

Before another source freeze, the prospective revision changes critic targets
from entropic CE gains to raw decoded task utility gains. A fixed TRAIN-only
paired stop/continue measurement estimates complete marginal service CPU,
including real output encoding. Its median, zero-clamp and global-price scaling
are fixed in the plan. No threshold is chosen from validation. Calibration
consumes actual control-system budget; static systems do no unused probes.

Every arm may continue only its already selected models in affordable complete
seed rounds, retaining original Adam/RNG state. Future necessary work is reserved
with explicit operator inventories and training-only CPU estimates; actual caps
remain decisive. There is no validation stopping or LR/mode reselection. The
independent formal fold remains unconstructed and unopened throughout this work.

Before this revision's source freeze, 114 independent tests passed in 5.019
seconds (exit 0). Coverage includes real native stop/continue output paths,
complete helper inventory conservation, original optimizer/RNG object retention,
unaffordable-round refusal, and seed-offset calibration binding. These source
tests use hand-built fixtures rather than the formal experiment test fold.

## Exact output-path optimization after t4

t4 exited 2 with control CPU-net -0.004656 and raw control/random -0.000356;
actual caps held and the formal test remained unopened. It retained an actual
calibrated v2 export/reload, PNG and checkpoint smoke; that did not close benefit.

A common output implementation now batches inverse-CDF sampling and pixel
quantization, preserving the exact draws, boundary behavior, sampled choices,
caption and PNG/JSON bytes. Every output still incurs real PNG encoding, hash,
base64 and serialization. No cached output or changed PNG compression is used.
The declared inventory increases by 40 units/request because all CDF comparisons
and boolean reductions actually execute; the code does not call vectorization
an arithmetic saving.

Five paired manual 64-request probes retained old/new CPU ns respectively:
21496228/10183211, 8865022/12723115, 14271004/14125451,
20811656/23839907, 14376616/12514530. Two pairs were slower. Median paired saving
was 145553 ns per batch, about 2.27 us/request; this noisy hand-array diagnostic
cannot establish whole-build, controller or held-out benefit. A new source freeze
precedes any actual training/validation use; prices, objectives, caps and gates
remain unchanged.

The output revision's 59 affected source tests passed in 3.506 seconds. Its t5
build exited 2: validation content A-anchor utility +0.014986, NDU-additive
+0.012584, control CPU-net versus NDU/full -0.002427, and raw control/random
-0.000780. Actual build caps held and the test remained unopened. Savings funded
84 residual control rounds versus 45 static NDU rounds; control had more final
updates for all three seeds but still a -0.001265 full-content utility gap.
These optimization trajectories and rare early-stop losses call for TRAIN-only
grouped decision-regret diagnosis before assuming a larger head is necessary.
No prospective nonlinear head has been committed, frozen or evaluated.

## TRAIN-only decision-regret diagnosis after t5

An exclusive START protocol preceded a single physical-source grouped four-fold
critic diagnostic. It compared exactly three fixed methods on TRAIN only: the
original 31-feature MSE ridge, a hidden-state/instruction affine MSE ridge, and a
loss-weighted classifier on the original features. No model or selection bytes
changed. The fixed content encoder had already seen all TRAIN sources, so this
is critic cross-validation, not independent content generalization.

Original ridge regret was 0.001452852795; hidden/instruction affine regret was
0.001078681362, about 25.75% lower. Its raw route gain over always-full was
+0.000371247790 and positive for all three seeds, with one seed only +0.00000365.
The weighted classifier always continued and gave no learned routing benefit.
The label-known oracle's raw advantage was only +0.001449929152 on this TRAIN
probe; those labels are unavailable at serving. No outlier was removed.

The diagnostic executed 36 fits and six actual 202-dimensional content forwards,
costing 549944880 declared units and 0.783566380 process-CPU seconds. This is
explicit development cost, not a held-out result or an unreported search inside
a qualified final build. All prior failed builds remain separately retained;
there is no claim that cumulative research budgets were equal. The prospective
builder fixes the chosen affine representation before source freeze and charges
its complete real fitting, calibration and inference work to control.

The evidence supports this smaller representation repair before any MLP. It
reuses the already computed thumbnail hidden state plus the original instruction,
fits the same raw full-minus-low target and ridge regularization, and retains the
same CPU-calibrated decision price, total caps and all existing benefit gates.
Positive TRAIN results do not guarantee validation readiness or formal benefit.

The affine integration's final 143 independent source tests passed in 4.836
seconds (exit 0), including real C/Python state, gain, route, work and reload
parity. The preceding check exited 1 because its test spy tried to assign a
method on a frozen dataclass; only the test spy was corrected. Production
equations, budgets and guards were not relaxed. The old C entry points retain
their argument lists; an old library lacking the new state/gain entry points
rejects an affine request before execution instead of using an unsafe ABI.

## Preparation forecast after t6

t6 exited 2 with real affine control/raw-random utility +0.001884 and joint
success +0.001971, but complete control/NDU CPU-net -0.014405. All actual caps
held and the test stayed shut. Content NC/full trailed NDU/full by 0.017696;
the control models received only 164/172/169 updates and no residual rounds.

Actual shared preparation cost was 6.543093432 CPU seconds, including compiler
CPU 0.916755295. Its broader slowdown has not been causally explained. The TRAIN
calibration retained a full-mode preparation maximum of 136.988070 ms for seed23.
The old scheduler repeated this maximum for all eight future control measures,
contributing to a 2.363858-second tail forecast. Actual subsequent fit/calibration
and selected/random validation CPU was 0.879944 seconds. This is conservative
reserved opportunity cost, not falsely charged work. Old receipts retained only
the maximum, so that historical sample distribution cannot be reconstructed.

The next fixed forecast retains all three actual TRAIN preparation samples and
uses `m*median + max(0, maximum-median)` for m future preparations. It reserves one
observed excess above the central repeated-work estimate, does not choose a
minimum, and applies the same formula to every arm. For a static model with one
future measure this equals the old maximum. Raw samples and every forecast term
are retained. This estimate cannot guarantee future execution times: actual full
cost, unchanged caps, phase guards and nonzero failure rules remain decisive.
No reward, head equation, threshold law, price, data or benefit gate changes.

## Shared preparation and accounting after t7

The preparation-forecast build exited 1 before completing any candidate. Its
actual shared CPU was 9.077421498 seconds; the frozen admission guards correctly
refused further work. No model selection, controller fit or formal test occurred.
The raw failure remains retained. A single protocol-first cProfile diagnostic
subsequently ran shared TRAIN/validation preparation once, including fresh native
compilation, in 4.001949343 attributed CPU seconds. All three base files were
byte-identical to t7. The slowdown did not reproduce; its cause remains unknown.
This debug execution is separate development cost, not a qualification retry.

The profile identified actual ledger-summary work. Incremental totals can avoid
repeated stage summation while preserving counters, snapshots, prices, atomic
budget rejection and source freezing. The first five-pair hand-array benchmark
retained exact old/new model, Adam, loss and receipt equality. Pure ledger CPU
had median paired saving 46.27%, but full 256-update CPU had median paired saving
-2.76%, with three of five pairs slower. Its thread environment was unset and
its twelve artificial prefix stages did not reproduce the real shared ledger.
These limitations do not establish the cause of the negative timing or erase it.
A single prospective corrected measurement fixes the normal one-thread profile
and uses the retained seven-stage shared counters, without creating experiment
data. It cannot establish whole-build benefit or historical slowdown repair.

Before that diagnostic, all 151 independent source tests passed in 4.708 seconds
(exit 0), including cache/stage-sum equivalence, late overflow rollback, shared
digest-failure atomicity and completed-shared metadata persistence on failure.
The test fold remains unopened; no cap, price, objective or benefit gate changes.

The corrected diagnostic executed once with all three thread variables set to 1
and observed one thread. Every pair retained exact snapshot, parameters, Adam,
loss and update equality. Ledger median paired saving was 15.54% (one slower
pair); actual 256-update median paired saving was 4.12% (two slower pairs,
including a -24.58% outlier). Aggregate update CPU was almost equal:
707.475291 versus 706.408365 ms, only 0.15% saved. All original and corrected
positive/negative timings are retained; no further benchmark was run.

The actual source-frozen t8 build then exited 1 with shared CPU 12.274880402
seconds, exceeding the unchanged 10-second cap before any candidate completed.
Declared shared units remained 3611371737. The previously missing full shared
metadata is now retained even on that early failure. The optimization did not
close the resource blocker and no identical-source retry or formal evaluation
followed. The retained receipt supports further component-cost diagnosis; the
historical runtime variation is still unexplained.

One subsequent timer-only shared diagnostic was declared and committed before
execution. It called the unchanged `prepare_shared` once, ran no candidates or
test construction, and retained every full calibration result. Its 43 disjoint
high-level spans accounted for 2.506054746 of 2.528051049 observed process-plus-
child CPU seconds, leaving 0.021996303 seconds of explicit residual. All three
models and the native library matched t8 bytes. A real 169ms output-encoding
outlier remained in the 27 calibration calls, without deletion or remeasurement.
The historical multi-second slowdown did not reproduce; no cause or repair is
established, and no subsequent qualification attempt was made. This diagnostic's
setup/execution and administrative persistence are separately retained R&D cost,
not a credit against any qualified build or an assertion of matched cumulative
research budgets.

## Bounded launch diagnosis and local reuse after t8

One precommitted two-pair AB/BA TRAIN-side probe compared direct launch with the
idle Python parent used by t8. All four fresh shared builds were retained:
direct A1 2.600737883s, nested B1 2.106176126s, nested B2 2.468531881s, direct A2
2.595229415s. Every start/end numerical snapshot agreed, and all 344 span
boundaries observed one task, OpenBLAS 0.3.30 with one configured thread and the
same affinity/backend bytes. All twelve base files and four native libraries
matched t8. Nested launch was faster in both pairs; these two pairs do not
establish causation, but do not support blaming the idle parent for t8. Its own
process CPU already exceeded ten seconds before adding compiler children.
Source verification and imports were recorded separately from shared work;
this did not reproduce the full train/check_freeze entrypoint or its boundaries.

The four diagnostic shared phases cost 9.770675305 CPU seconds and 14445486948
declared units. Recorded cumulative worker CPU was 11.732311824 seconds, with
0.001457611 seconds of nested-parent own CPU separately recorded. All fast and
slow samples were kept in a per-file-verified lossless archive. These are R&D
costs, never credits against a qualified build or an assertion of matched
cumulative research budgets. No qualification ran during this diagnosis.

Three concrete implementation changes now precede a fresh source freeze:

- Adam looks up existing moments before allocating zeros. The unchanged shared
  schedule previously allocated 21600 zero arrays; only the initial 48 are
  needed. This avoids 21552 arrays, 26298096 zero elements, about 210MB cumulative
  allocation traffic (not peak memory). The earlier profile's zeros_like time
  was only 0.094s, so this is not an explanation of the multi-second slowdown.
- Each three-mode validation prepares one local actual decoder observation and
  reward rather than six repeated preparations. Selected scoring prepares the
  normal observation once and actually decodes the corrupted decoder separately
  (three preparations become two). The same semantic formulas are shared with
  legacy wrappers. Deleted arithmetic is also removed from actual charges and
  future inventories; no outputs, PNGs or input-dependent content are cached.
- Low/full TRAIN critic targets reuse one indexed reward tensor, avoiding a
  second identical roughly 3.54MB copy per selected seed. Both actual utility
  computations and their arithmetic charges remain.

These are small, equation-preserving savings; no claim is made that they close
the content opportunity-cost or effective-control benefit gap. Once-per-build
same-process numerical metadata is now captured inside charged shared CPU and
retained with selection/telemetry, including optional discovery errors. It
observes backend/thread configuration without changing it.

Final verification passed 49 root tests (0.276s) and 157 independent tests
(4.594s), exit 0. The first independent check had one error: a new diagnostic
file write preceded a deliberately injected kernel failure. Discovery now stays
in the charged phase while persistence uses existing final receipts, preserving
the original error; 28 affected tests and the corrected full suite passed.
Both failed and corrected logs remain retained. No test fold was opened.

## Unit-limited t9 and folded adaptation

The local-reuse build completed with exit 2. All CPU/work caps held; complete
CPU ranged from 5.337 to 6.159 seconds. Validation A-anchor utility was
+0.023051956962, NDU-additive +0.004811200382, and control/random +0.001311078897,
but control/static-NDU complete CPU-net remained -0.002094252134. Same-weight
routing helped; NC/full content trailed NDU/full by 0.003729004304. NDU/control
received 386/367 updates per seed. Candidate and residual receipts establish
operator-allocation refusal, with CPU headroom. All three shared bases matched
t8 bytes. The failure, exact decomposition and standalone RGB/reload smoke were
retained before further implementation; no test fold was opened.

The next candidate removes redundant encoder arithmetic in already expanded
low-view adaptation rows. It keeps shared decoder300 and dense pretraining500
unchanged, preserving fixed common base weights. The existing random indices,
view mask, np.where inputs, 202-dimensional trainable encoder, heads, objective,
optimizer and decoder remain. Each step freshly folds four repeated-pixel
weights into a 58-feature low encoder, then expands its low encoder gradient
back into the original parameter map. This is real-arithmetic equality with
changed floating reduction order; mixed adapted-weight bytes can differ.

The componentwise envelope is used only for pre-RNG admission. Actual mask
geometry determines the atomic charge, including fold, replica checks, mask
scans and gradient merge. The actual objective-step ledger delta determines
CPU/unit forecasting; the envelope is never billed as executed work. Gather,
scatter and copies remain inside actual CPU. Shared base training never passes
the optional mask, while every continued-training arm uses the same profile.

At n64/h32/32 low rows, the declared inventory removes 294912 encoder MACs and
adds the actual scalar/check work: net 573952 units versus the previous dense
step, about 24.88% of an NDU step. This is an operator estimate, not a CPU or
content-gain measurement. Small split GEMMs and memory traffic may offset CPU
savings; all real cost and the original gates remain decisive.

The numerical tolerances in TRAINING_KERNEL.md were fixed before any numerical
execution and were not relaxed. Five new hand-array tests and 25 affected
learning/accounting/optimizer tests passed, plus 41 runner/forecast hand tests.
The final complete independent suite passed 171 tests in 4.991s, exit 0. It
covers dense/all-full bitwise behavior, mixed gradients/Adam, fresh folds,
clipping, custom-price envelope safety, atomic rejection, unchanged RNG draws,
whole-seed-round admission and actual-unit forecasting. A new immutable source
freeze must precede the next actual TRAIN/validation build. No benefit, speed,
extra updates or acceptance has yet been credited to this kernel.

## T10 CPU constraint and adaptation-only optimizer

The frozen folded-adaptation build exited 2. All caps held, shared bases matched
t9 byte-for-byte, and every selected content model changed all 7288 entries.
NDU reached 636/637/637 updates, NC 490/475/402; the arithmetic savings became
real updates. A-anchor and NDU-additive validation utility remained positive at
0.017316017337 and 0.004722618475, but complete NC-static net was -0.002650369319.
The saved decomposition is content -0.003445684603, own-weight routing
+0.000446690712 and complete CPU contribution +0.000348624573. More updates are
not guaranteed to close that content gap. T10's actual shared CPU was 3.122s;
the historical slowdown remains unresolved.

All nine NC candidates stopped on CPU admission despite room for the next
operator envelope. A/N/NC residual rounds also stopped on CPU forecast/guard;
S/H were unit-limited. This differs from t9's unit-limited execution. The failed
run and all 80 raw files were losslessly archived with per-file size/hash checks
before any removal, then pushed in commit 278f3bed09. No formal data was opened.

The next isolated candidate uses adaptation-only native Adam to remove repeated
temporary arrays and Python dispatch, preserving original element expressions,
Python norm/clip/power denominators, clocks and per-step arithmetic inventories.
Preparation scans are charged and reserved; compilation and binding stay inside
complete CPU. Shared dense base/decoder training stays on its unchanged NumPy
path. All five adaptation arms use the same adapter. See ADAPTATION_OPTIMIZER.md.
Three hand-array tests prove exact parameter/moment bytes; the final independent
suite passed 180 tests and root suite 49. An initial compiler-mock fixture failure
and all corrected logs remain retained. No speed or content benefit is credited
before a new immutable freeze and actual build; original gates remain unchanged.
