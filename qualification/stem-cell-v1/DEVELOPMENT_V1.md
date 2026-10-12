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
