# Six-stage Cell development: first executable operator slice

Frozen source: `c87fa42558b7242fb560d50857b613d21e20cddb`, existing
`research/stem-cell-three-experiments-20261011`. Separately read FBSDE research
PR #1550 at `66258d5871cd022c0fa13995dd6ba787b4d2359e`; its changing 131-file
research stack is NOT silently merged, replaced or represented as tested here.

This is research code in the EXISTING qualification directory, not a second
runtime, trainer service, state store, artifact registry or authority. None of
the six production/efficacy gates is closed by this operator slice.

## Mechanisms and explicit completion boundaries

| Stage | Actual source in this change | Not established by these tests |
| --- | --- | --- |
| Shared Stem / Cell learning | Existing `SharedStemEngine` and `model_runner.build_head/train_head` composed by `development_trial.py`; paired same-initialization frozen/trained Heads, whole-trial scope/version preflight and actual Encoder call accounting | Pretrained-model gain; wall/RSS/energy advantage at equal quality; production native Worker scheduling |
| Split / merge / sleep | `BasisCellHeads` shares an organ basis with 2r+1 local coefficients per Cell; next-generation function-preserving split, exact-only merge, explicit dormancy and optimizer-isolated local training | Data-driven structural selection, superiority to larger Heads/more data, independent future gain, native checkpoint CAS or migration |
| Shared recurrent computation | One GRUCell repeatedly reads a masked workspace; caller-owned input/output state, fixed bounds, no parameter multiplication by depth | Semantic reasoning superiority to best fixed depth, a cheap exact solver or production System 2 |
| Multimodal differentiation | Trainable connectors consume frozen text/image/video/audio tower tensors, retain individual tokens and declared timestamps, reject future/reversed times, keep text identity and freeze input gradients | Any real pretrained tower, learned cross-modal relationship quality, validated timestamp/source authenticity or temporal dataset |
| Generation / NDU control | Fixed linear utility-cost special-case continuation selector with stop; actual output-byte/digest/budget checker and externally supplied verifier; failed verification remains charged | A new generator, actual text/image/video/audio generation, independent semantic attestation or a general FBSDE solver |
| Cross-Cell consolidation | Bounded KL teacher distillation into shared basis/readout on a candidate copy; group-level descriptive retention diagnostics | General retention, future transfer, signed acceptance, safe production base consolidation or 10T/100T equivalence |

## Corrected real batch defect

Before this change, a hit was counted but not retained outside the LRU. Cold
insertion could evict that hit before its request was resolved, producing
`unresolved feature after backend invocation` for a valid same-scope batch.
The invocation now borrows immutable hit references alongside cold results.
No additional Encoder call or cross-scope reuse is permitted. The LRU size
remains bounded; borrowed invocation-local references are transient memory, NOT
included in `cache_bytes` and NOT a claim of bounded process RSS. Existing
1..32 batch and feature-width bounds still apply. This is not thread-safe
revocation serialization; the trusted production owner remains responsible.

The original source blob was reconstructed byte-for-byte and verified against
Git blob `f69b324e0b84f6582f86662e6afa6b8097dfd001`. Two of the five new cache
regressions reproduce the original failure. All five pass after the small fix.

## Learning, parameters and cost

The Encoder is never copied into a Cell bank. At rank r the private learned
coefficient and gate storage is 2r+1 scalars per Cell; this intentionally limits
expressivity. Shared basis/readout storage, runtime state, optimizer state,
training and future validation are not free or folded into that count.
Split clones one small candidate bank once, not one bank or Encoder per child.
This is not a zero-copy checkpoint CAS implementation. Nonidentical merges are
rejected instead of silently averaging specialist weights.

Local training exposes only one Cell's private parameters to the existing
fitter. Zeroing peer gradients alone would not protect their nonzero weights
from AdamW weight decay. The original selected bank and peer weights are tested
for byte-exact preservation. Live selection is never changed by these methods.
Distillation uses detached teacher probabilities and temperature-scaled,
batch-mean KL, and trains only shared basis/readout parameters. Teacher data,
preparation costs, old-task replay and held-out evaluation belong to learning.*.

The shared trial accepts ONLY caller-constructed training-label mappings and
returns paired held-out logits without reading their gold labels or scoring
itself. Callers MUST first use the canonical dataset/group/time qualification;
this low-level function does not authenticate training-fold provenance. Its
in-process diagnostic parameters `head_factory`/`fitter` exist for tests and
must not be wired to untrusted plugin code. No remote code/model download path
is added. Wide representations remain explicit; this floating-point research
Head does not bypass native V1's 512-feature admission or Q24 conversion.

## Owner integration contract (unchanged)

`inference.control` owns real Stem/tower/generator execution, batching, final-use
and physical accounting. `neuron.runtime` owns Cell state/checkpoint CAS.
`intelligence.control` owns bounded group/Organ workspace calls. `utility.ndu`
owns the fixed registered recursive valuation profile, not generated truth.
`learning.*` owns experience, fitting, independent outcomes and immutable
candidate artifacts. Topology and shared-parameter changes require compatible
next snapshots and independent selection. No production owner is implemented
or superseded by these Python operators; signed CAS/WAL/recovery stay mandatory.

## Reproduce and interpret

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  test_shared_encoder_eviction development_tensor_checks
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  development_repository_checks
```

Torch-specific checks deliberately have no `test_*.py` name: the separate CPU
workflow installs the required Torch dependency and runs them explicitly, while
the existing dependency-free lane still discovers all cache regressions. This
is not skipping a missing dependency: the new lane fails if Torch cannot load.
It tests both actual PR source and the prospective merge, preserves failures
and never changes any global/native, security, or production release gate.

Local evidence on Python 3.13.5 / Torch 2.10.0+cpu: the first command executed
31 tests, zero failures and zero skips. Synthetic features, a small actual
optimizer, shared recurrence and connector gradients are mechanism evidence,
NOT real mmBERT/Jina/model runs. The repository-entrypoint checks require the
complete checkout and must be read from their exact CI source SHA; they were
not executed in the partial local source reconstruction. No pretrained weight
or future Hepta dataset was available locally. No production activation.

## Second executable slice: controlled learning, generation and native skills

Parent source: `a9bd346198a2dddb5e67ed1bfcf42c1402dcff3b`, which already
preserves upstream Worker resource/quarantine fixes. The first-slice evidence
above is retained, not relabeled as a new run. New files stay under this existing
qualification owner; the existing CPU workflow is extended, not replaced.

`development_sharing.compare_shared_encoding` composes the actual existing
`SharedStemEngine` in three independently cold-cache arms: singleton/no-cache,
batch/no-cache, batch/cache. Alternating arm order, whole-study scope/version
preflight, actual backend calls and strict batch/solo numerical comparisons are
recorded. Use the existing approved local HF backend for real weights; a mock
still reports `simulated_encoder=true`. Model load, complete runtime RSS and
end-to-end same-quality acceptance remain separate. The original
`development_trial` still supplies independently trained per-Cell Heads.

`development_ablation` trains private candidates with explicit parameter bytes,
steps, processed examples, CPU and wall time. Structural arms are unchanged
parent, inherited split, a larger Head within the split's local trainable budget,
and more data. The latter intentionally consumes more actual examples, which is
reported rather than called equal work. All see the observed route bit; a parent
that ignores it is not a universal best unsplit architecture. The larger Head
control can use it. Frozen shared-basis parameters and their costs remain visible.
A split win here cannot establish optimal architecture, lifelong gain or promotion.
The reusable recurrent classifier is trained with real gradients and evaluated
at several fixed depths against a deliberately retained exact cheap comparator.

The finite NDU allocation candidate extends the earlier one-step selector to a
bounded public-information DAG. It computes conditional expectations, includes
stop, charges every path's acquisition cost and supports complementary multi-step
observations. The profile is ONLY conditional expected utility minus cost, not a
neural/general FBSDE solution. Public-history provenance is externally required.
Missing states, cycles, duplicate histories, invalid probabilities, depth >32 or
>8192 state/budget pairs reject. Resource decimal budgets use exact rationals so
0.3 minus 0.1 still affords 0.2. Utility arithmetic remains floating-point.

`development_generation` adds an actual shared autoregressive GRU/readout, four
lightweight modality scale/bias heads and next-token training. Teacher forcing
is a training-only interface. Greedy generation receives no target payload;
EOS is learned, completed rows stop computing, malformed/unterminated outputs
stay failed and are never repaired from a target. The explicit byte codecs are
UTF-8 text, grayscale PGM, monochrome Y4M video and PCM8 WAV audio. The synthetic
study learns tiny conditional payloads. It is NOT a pretrained image/video/audio
model, a natural-language reasoning system or broad multimodal quality evidence.

`development_native` lowers a CLOSED affine/select decision IR into LLVM MCJIT
and executes the emitted CPU function. It accepts no raw LLVM, binary code,
arbitrary pointers, loops, syscalls or GUI effects. Result integers are proposals,
not capabilities. Compiler/LLVM/target/CPU-feature identity, object digest/bytes,
cold compilation, bounded process-local cache and hot wrapper costs are recorded.
This is NOT a sandbox for arbitrary generated native programs. The existing
Worker/Final-use owner must independently admit any later effectful integration.
The matched comparison retains typed interpretation and JSON-roundtrip controls;
the JSON control is NOT called MCP. Wasm, GPU and computer-use E2E are NOT RUN.
No native speed advantage or compilation amortization is presumed.

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  development_ablation_checks development_sharing_checks
PYTHONPATH=qualification/stem-cell-v1 python3 \
  qualification/stem-cell-v1/development_experiment.py --synthetic \
  --output /new/external-study-directory
```

The study preserves generated payloads, source digests, all actual native timing
samples and failure records in an exclusively created external output directory.
Metrics are descriptive synthetic diagnostics, not independent future-window
NDU or measured pretrained Stem outcomes. Total local study time is recorded
separately from overlapping phase spans; do not sum nested spans or treat them
as energy, RSS, model acquisition, dataset preparation or lifetime cost.

Local Python/Torch/LLVM mechanism validation executed 26 additional tests with
zero failures/skips. The three sharing composition checks require the complete
repository; their exact-head hosted verdict is separate and was not asserted
locally. The first synthetic run also retained negative results: deeper recurrence
was not always better, the exact cheap rule remained stronger, and tiny-policy
native JIT was slower than typed interpretation. These outcomes are not discarded.
Hosted source-head/prospective-merge, global Rust/Bazel/security, physical pretrained
weights, independent future evidence and actual production owner recovery remain
mandatory before broader acceptance. No main merge or production activation.

## Third slice: fair specialization and paid computation reuse

Parent: `d32914a10f847a35aaf127ac47c29a162e43f0d6` / existing Draft PR #1648.
The earlier reports above remain historical observations. This slice changes
research operators only, not production execution or any authority owner.

### Correct the structural comparison before declaring a split win

`RouteAwareUnsplit` is one conditional Head with no Cell IDs or topology edits.
It receives the same public route bit, shared basis, initial function, local
parameter count and SGD stream as the split. At binary routes it contains the
split function exactly. This deliberately strong equivalence control separates
new capacity/information from the mere existence of a second logical identity.
The original weak parent, larger-Head and more-data arms remain visible.
`structural_arms` now REQUIRES separate `train_fold` and `holdout_fold`; scope,
source-family and chronological overlap fail before optimizer entry. Metadata
is caller-supplied and is not authenticated provenance. Synthetic logical times
are not real future windows. Existing callers and regression tests are updated.

Actual fixed-seed synthetic held-out accuracies: split 0.75, route-aware unsplit
0.75, and route-aware unsplit with more data 0.875. The former comparison against
a route-ignoring parent therefore does not establish a split-specific advantage.
This does not rule out lifecycle, transfer or scheduling benefits of real Cells;
those require their own comparisons. Whole state-tensor bytes and actual training
examples are reported, including frozen shared tensors rather than just deltas.

### Reuse recurrence, not evaluation work from another arm

`incremental_depth_candidates` pays for one recurrent prefix and keeps each
requested depth's own readout. Fixed-depth controls are still independently run.
Neither path changes the selected model's `depth` attribute; the explicit depth
argument removes temporary shared configuration mutation. In the 16-case fixture,
independent depths 1/2/4 execute 112 state transitions versus 64 for shared prefixes,
with exactly equal logits at each requested depth. Counts are not a wall-time,
semantic reasoning or general NDU improvement claim. Per-arm CPU/wall measurements
remain separate; cumulative/nested spans must not be added as independent costs.

The generator study now runs zero-condition and within-modality permuted-condition
controls without passing target bytes into inference. All their inference work is
charged. Full conditions recover 16/16 tiny payloads, zero conditions 2/16, and
permuted conditions 0/16. These remain tiny repeated concepts, not broad multimodal
understanding or unseen-concept generalization. They test conditioning dependence,
not independent semantic correctness or realistic video/audio generation quality.

### Native execution: admit immutable programs, still validate every input

Both `PreparedDecision` and compiled execution validate static IR once and retain
a detached private snapshot. Public `program` returns a copy and has no setter;
replacing its width can no longer resize buffers for a differently compiled ABI.
This is not protection against arbitrary Python/ctypes code in the same process.
All dynamic input type, finite-value, range, shape and batch checks remain active.

The only new loop is compiler-emitted and bounded to 1..32 rows. Whole-batch
preflight precedes one actual native FFI call; malformed late members do not
partially dispatch. Cache eviction keeps outstanding executable objects alive.
Typed interpretation receives the SAME static-admission optimization: it is not
an intentionally slow per-call-IR-validation strawman. Native error does not
silently fall back or retry. No syscalls, GUI effects, new grants or raw code inputs.

`development_native_benchmark.py` measures fixed policies on identical observations,
rotates backend order, keeps every timing sample and charges validation/marshalling.
It reports whole-batch p50/p95/p99 and throughput, NEVER batch time divided by rows
as request latency. Cold per-policy admission and extra admission amortization are
separate; LLVM itself may already be warm within a process. Verification is timed
separately and total benchmark time includes it. No queue or computer-use E2E claim.

Three fresh-process runs on the same final benchmark source/inputs show: 32-row
complex guard scans improve median batch latency by 6.72..7.00 times versus the
prepared typed control; tiny and medium policies remain slower in native code.
The guard-scan profile is explicitly branch-heavy, not a representative workload
claim. Local unsigned host noise is visible in the retained p95/p99 samples.
Compile admission amortizes after an estimated 74..82 such batches in these runs;
nonpositive-saving cases retain null amortization. Do not always choose native.

### Executed checks and remaining physical gates

45 local tests passed without failures/skips, including all 26 prior Torch/LLVM
checks, 16 new regressions and the three previously unexecuted sharing checks.
The latter now run against exact original SharedStemEngine/cache-accounting Git
blobs, but their Encoder is still explicitly simulated. This is a sparse checkout,
not a full Rust/Bazel/global CI result. The existing workflow keeps all original
checks and adds the new tests/benchmark for exact source and prospective merge.

No approved model snapshot was supplied locally and direct model downloads failed.
No weights were fabricated and the existing safetensors-only loader was NOT relaxed.
Real pretrained task quality, independent future NDU, 64..4096 target-host resource
measurements, GPU/Wasm/MCP/computer-use E2E and production Final-use/WAL recovery
remain unaccepted. Remote checks must finish on the actual latest SHA.

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  development_ablation_checks development_native_batch_checks development_sharing_checks
PYTHONPATH=qualification/stem-cell-v1 python3 \
  qualification/stem-cell-v1/development_native_benchmark.py --output /new/native-study
```

## Independent quality floors and shared anytime supervision

Parent is `723f65adc2f2cd9ef007e95e78b8c532f44b7708` on existing Draft PR #1648.
The earlier studies are retained as historical evidence. This continuation adds
research functions to the existing qualification owner, not another registry,
NDU subject, runtime authority, or production selector.

### Stop quality is a constraint, not a cheaper way to lose correct answers

`development_quality.py` freezes baseline/candidate identities before a fifth
fold protocol: model-fit, critic-fit, calibration, independent risk, then heldout.
Baseline fixed-depth/confidence controls and the naive learned threshold are
chosen on calibration only. Risk labels never enter the executor, and heldout
labels never choose a threshold, model or fallback. All policies and declared
subgroups are tested; incomplete panels, wrong ordering/digests, missing rows,
foreign groups, duplicate content across purported independent groups and
chronological overlap reject. Missing declared strata cannot pass.

The tested event for source group g is H_g = 1 if ANY baseline-correct answer in
that group becomes candidate-wrong. Improvements on other answers do not cancel
H_g. Correlated rows count as one group. With n IID groups and k harmful groups,
the one-sided Clopper-Pearson upper bound solves BinomialCDF(k;n,p)=alpha/M,
where M counts every candidate and overall/stratum test. Zero observed harms
still have upper bound 1-(alpha/M)^(1/n), not zero. A literal zero-harm tolerance
retains the baseline; finite data alone cannot certify a different policy at
zero risk. The implementation uses log-space CDFs and conservative bisection.
Exact small-binomial probability enumeration independently checks coverage.

The demonstration uses a preregistered 2% harmful-GROUP event bound, NOT absolute
2% error, exact same quality, a row-weighted population claim or product policy.
With IID groups, the group-mean extra error is bounded by this event probability.
IID/source provenance and distribution stability are assumptions, not verified
by hashes. Alpha is allocated across all seeds and, for paired training, both
training variants. Timing floors are explicitly empirical, not confidence bounds.
This is a conservative Learn-then-Test special case, not a general NDU theorem:
Angelopoulos et al., https://arxiv.org/abs/2110.01052 .

After quality testing, a candidate must also save at least 5% median measured
wall time and be faster in every matched repetition. Static identity checks,
input hashing, dynamic validation, recurrent execution and output construction
are timed for ALL policies. Repeats rotate policy order and charge every run.
Compilation/model initialization, native device resources and energy are not
measured. Costs and nested total-phase times must not be summed twice.

`development_quality_runtime.py` calls the existing `run_stopping`; it does not
replace its state transitions. Bindings include model, critic parameters and
unit-cost profile, threshold, execution-source bytes and runtime identity. Entire
populations are validated before the first microbatch. Only the preselected
policy runs on heldout data; exceptions propagate without trying another policy.
Python dataclasses are NOT cryptographic authorization or protection against
arbitrary in-process code. Live owner serialization, CURRENT, Final-use, revocation
and WAL remain separate product obligations.

### Learn usable intermediate outputs instead of just scheduling weak exits

`development_anytime.py` trains the EXISTING GRU and shared readout against the
same training labels at all four depths, with fixed equal loss weights. It adds
no per-depth model, Head bank, parameters or private optimizer service. Training
uses the same initialization, rows, SGD stream, learning rate and step budget
as the terminal-only reference. Four readout/loss evaluations cost more than one;
actual CPU/wall, readout rows and recurrent transitions are reported. A terminal-
only weight vector reproduces the existing fitter's parameter updates in tests.
Inputs and original selected parameters stay unchanged.

### Executed evidence and retained negative results

95 local sparse-source tests pass: 62 retained plus 33 new. These include exact
risk-bound checks, stratified failures, zero-tolerance fallback, source/critic
mutation refusal, no partial dispatch or fallback after an exception, real GRU
execution counters and actual multi-exit gradients. This is NOT full repo CI.

The first three 512-row heldout studies retain baseline accuracy/counts exactly:
101: 0.93359375 / 512; 202: 0.927734375 / 868; 303: 0.939453125 / 862.
All four learned candidates fail either a quality slice or the empirical cost
floor, so all three selections retain baseline. Naive stopping on seed 303 uses
649 transitions but scores 0.912109375; lower work is not counted as qualification.

Before running the new training comparison, fix fresh seeds 404/505/606 and both
training variants. The three paired calibrated-baseline results are:

| Seed | Terminal-only accuracy / transitions | Anytime accuracy / transitions |
| --- | --- | --- |
| 404 | 0.939453125 / 926 | 0.916015625 / 972 |
| 505 | 0.92578125 / 979 | 0.943359375 / 512 |
| 606 | 0.9375 / 512 | 0.939453125 / 512 |

These are descriptive synthetic comparisons, not an accepted cross-model
improvement. Each guard uses its OWN frozen baseline; it does not certify an
anytime model against the terminal-only model. All six guarded selections retain
their baseline. The cheap exact task rule is still 100% correct. Keep the seed-404
regression and all extra training/selection costs; do not select a training method
using heldout results or claim that deeper supervision is universally better.

All risk predictions and full timing schedules are saved before risk scoring;
all heldout predictions are saved before heldout scoring. Initial and final
studies remain separate, source-hashed, create-only outputs. The existing CI lane
adds both studies and all new tests without removing old tests, native benchmarks,
source-head/merge lanes or global Rust/Bazel/security gates. Exact remote results
are still required. No approved pretrained snapshot was obtained; local DNS and
public-download attempts failed. No fallback weights or unsafe loader changes.

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  development_quality_checks development_quality_runtime_checks development_anytime_checks
PYTHONPATH=qualification/stem-cell-v1 python3 \
  qualification/stem-cell-v1/development_quality_study.py --synthetic --output /new/quality-study
PYTHONPATH=qualification/stem-cell-v1 python3 \
  qualification/stem-cell-v1/development_quality_study.py --synthetic --paired-anytime \
  --output /new/paired-study
```
