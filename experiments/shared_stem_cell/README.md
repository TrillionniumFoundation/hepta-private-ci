# Shared Stem / Neuron Cell experiment suite

This directory is the experiment control plane for the six experiments in the
shared-Encoder + Cell-specific gated Head proposal. It is research-only:
`production_accepted` is false for every emitted receipt and no runner may
select, activate, promote, or release a model, topology, or executable.

The suite tests whether one frozen Stem plus small Cell adapters can deliver
better utility per active resource than replicating complete models. It does
not infer equivalence to a 10T or 100T parameter model from parameter count.
Conditional routing, external memory, distillation, and specialist decoders
can match a bounded task distribution, but general capability equivalence must
be established by independent held-out evaluations and is not assumed.

## Experiments

1. `scripts/memory_cell/stem_selection_experiment.py` compares small, medium,
   421M and replicated-421M arms under a common budget.
2. `scripts/memory_cell/reader_four_arm_diagnostic.py` evaluates no evidence,
   ordinary retrieval, sufficient verified evidence, and deleted-premise arms.
3. `experiments/shared_stem_multimodal_system2/multimodal_ndu_runner.py`
   summarizes modality-pair results and the five System-2 ablations.
4. The same runner rejects an internal NDU score when external task outcomes
   or resource measurements are missing.
5. `codex-hepta-plasticity` exposes proposal-only Cell split candidates with
   state migration and retained-task gates.
6. `codex-hepta-compiled-use` exposes a fixed five-action ABI, a bounded ring
   queue and a deny-by-default sandbox interface. It never executes arbitrary
   bytes or writes executable memory.
7. `experiments/shared_stem_head_matrix/runner.py` compares linear, gated,
   LoRA and sparse-expert Cell Heads under one frozen Stem and active workload.

## Required reporting

Every arm must bind exact source/model/preprocessor/Head digests, dataset split,
host profile and measurement interval. Report task utility, active FLOPs,
latency p50/p95/p99, resident memory, peak memory, negative transfer, new-Cell
incremental cost, calibration/OOD, old-task retention and rollback status.
Missing measurements produce `insufficient_evidence`, not zero.

The canonical decision rule remains conservative: a candidate is retained only
when its independent lower confidence bound exceeds the baseline upper
confidence bound in the declared direction and all hard floors pass. Internal
NDU utility is diagnostic; it cannot substitute for task success.

## Suggested order

Run the reader diagnostic before tuning retrieval or Heads. Then select a Stem
with the four-arm resource/utility comparison, establish unimodal baselines,
add modality adapters and specialist decoders, run NDU ablations, and only then
generate offline split proposals. The compiled-use pilot is last and must use
typed actions, capability checks, signatures, W^X, resource budgets and
rollback; the slow MCP/tool path remains the authorization/control path.

## Actual execution increment

The existing Head matrix CLI now accepts `--execution-manifest`. This invokes
`execution.py`: a real local stock Hugging Face Encoder/MLM, four actually trained
per-Cell Heads, immutable same-initialization controls, and separately sealed
predictions. It does not reinterpret a Laya Decision model as a generic Encoder.
The low-rank arm is a post-Encoder residual, not a backbone LoRA measurement.
The legacy synthetic estimator remains explicitly labeled; imported observations
no longer inherit its fictitious incremental-parameter, memory or penalty values.

```sh
python -m experiments.shared_stem_head_matrix.runner \
  --execution-manifest /approved-input/manifest.json --output /new-output-directory
python -m unittest -v experiments.shared_stem_cell.test_execution \
  experiments.shared_stem_cell.test_browser
python -m experiments.shared_stem_cell.browser_loop \
  --output /new-browser-output-directory --tasks 24
```

The execution manifest schema is `hepta.shared-stem-execution.v1`. Required fields
are `classes`, `cells`, `dataset: {path, sha256}` and
`model: {path, kind, revision, files}`. Paths are relative to the manifest;
`files` maps every ordinary snapshot file to its actual SHA256. `kind` is
`encoder` or `masked_lm`, `revision` is a full 40-hex immutable revision. The
bounded safe loader requires safetensors, no remote code, a clean loading report,
and exact materialized tensors, including tied aliases. It rechecks source
material before publication; this is not independent host attestation.

Dataset JSONL rows contain exactly `case_id`, `group`, `split`, `observed_at`,
`cell`, `scope`, `text`, `label`. Use train/calibration/holdout and optionally
extra_train/retention. Groups and identical text cannot cross folds. Real
chronology is enforced only with `temporal: true`; missing times are not invented.
`steps`, `seed`, `batch_size`, `maximum_tokens`, `measure_sharing` and
`run_controls` bound the optional work. One physical study uses one Scope.
The producer's Head API receives train labels only. Scoring is a separate
post-seal operation, not an independent evaluator identity or acceptance.

`public_smoke.py` is the sole network-acquisition entrypoint. It resolves and seals
immutable public mmBERT-small and AG News revisions before downloads, hashes the
physical files, then runs that same local-only loader on 64 train, 32 calibration
and 32 held-out public records. Eligibility is fixed before label access. Public
record identity is NOT an independently verified source-family partition, this
is not a real future window, and no Laya/no-change superiority is claimed. The
exact-source workflow executes this public-weight path separately from fixtures;
an unavailable dependency, snapshot, download or model load is a failure, never
a synthetic replacement. Dataset selection, first download and model loading
costs are not represented as steady-state Cell latency.

`controls.py` performs actual candidate-only split/unsplit training, optional
extra-data training, ordered masked modality-connector training, shared GRU
recurrence with actual early termination, and shared-Head KL distillation. ALL
split controls receive the same observed route feature. The wider comparator's
parameter gap, inherited training and examples processed are explicit. Missing
extra data does not turn repeated examples into a more-data arm. The four
recurrent arms share one trained model and maximum depth; actual transitions
and time differ. The NDU candidate is ONLY a linear conditional expected
external-correctness gain minus cost profile, not the general FBSDE solver.
The public smoke refines one pooled observation, not a new multihop input trace.
An optional local `generator` manifest admits actual causal text generation with
no target-bearing generation API. Head distillation is not generator distillation.

`browser_loop.py` executes real Chromium on its private local form. It implements
an actual MCP stdio initialization/tools protocol subset with a resident child,
not a JSON-roundtrip surrogate. Typed steps, MCP steps, a closed typed two-action
program, and an equivalent MCP program use identical observation checks, browser
operations and fsynced lab journal. Each action verifies current generation,
sequence, observed state and element binding; programs re-observe between effects.
The page cannot fetch arbitrary URLs. Unknown post-dispatch effects quarantine
the lab owner and are observed/reconciled without replay. This is NOT the product
FinalUse owner, a general MCP implementation, cross-process crash recovery,
executable-memory/JIT/GPU execution or arbitrary website/desktop control.

### Measured local result and remaining six gates

The local final source slice ran 42 tests with zero failures/skips. Torch tests
use explicit test tensors, not pretrained model evidence. A separate real
Chromium 144.0.7559.96 study ran 24 private-form tasks per arm (96 whole-task
executions), all successful. Measured hot-path milliseconds:

| Arm | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| typed_steps | 58.720822 | 80.948145 | 101.593965 |
| mcp_steps | 59.404364 | 76.525162 | 88.336162 |
| typed_program | 58.258647 | 71.006575 | 72.661992 |
| mcp_program | 60.693465 | 76.905390 | 93.148944 |

No substantial MCP-removal advantage is established. Each tail uses only 24
samples; these are correlated, controlled form tasks, not independent general
computer-use reasoning. Cold startup is recorded separately. The earlier failed
fixture run is retained externally: repeated `set_content` redeclared top-level
JavaScript state and lost the handler; an IIFE fix plus reset/postcondition tests
repairs that defect without relabeling the failed run. Prediction seal for the
completed study: `a3c8b7387a43ba370ca54d89345822af093feb680bb39f0558e2fb4591ea3fb9`.

1. Real Stem: local execution code and training mechanics are present; the local
   container has no pretrained weights/network. Public hosted outcomes require
   their actual exact-source receipt. Laya/replication, 64-4096 Cell scaling,
   independent quality, peak RSS/FLOPs/energy and equal-quality selection remain.
2. Split: real training controls are tested; independent future net gain, durable
   topology migration and retained-task qualification are not established.
3. Multimodal: connector/mask/order operators are tested, but real pretrained
   media towers, authorized paired media and semantic/temporal results are absent.
4. System2/NDU: four executed tensor controls are available; general NDU/FBSDE,
   independent task improvement and equal-resource superiority are unverified.
5. Generation: a real offline text-generation call path and Head KL exist;
   pretrained generation has not run locally. Image/audio/video generators,
   new-concept quality and generator consolidation remain unimplemented here.
6. Computer use: real local Chromium/MCP measurement and same-owner fault tests
   ran; product FinalUse, unclean restart, JIT/GPU and general task evidence remain.

Missing energy, FLOPs, process peak RSS and GPU counters remain null; tensor
storage and current-process RSS endpoints are not substituted. All six acceptance
claims stay open. The runtime and durable owners remain inference.control,
neuron.runtime, utility.ndu, learning.*, the existing execution spine and FinalUse;
these research operators do not add a production service or privilege issuer.

## Continuation: material loading, media execution and controller crash recovery

This increment continues the same PR #1699 implementation, not another experiment
matrix. The original source was `3b9e743c45c808bb25712c0c583001943adb5599`.
All historical browser timings and limitations above remain historical; none are
relabelled as new model or product results.

### Explicit weights-only artifact conversion

The public mmBERT-small file inventory inspected on 2026-10-13 exposes
`pytorch_model.bin`, while the original acquisition downloaded only safetensors.
The previous real-weight lane therefore could not load that snapshot. The ordinary
`LocalEncoder` STILL requires safetensors and never falls back to pickle.

`checkpoint_conversion.py` offers a separate **explicitly accepted** conversion.
It checks the publisher's immutable LFS SHA256, then invokes an isolated Python
subprocess with Torch >=2.10 and `weights_only=True`, no added safe globals and
CPU/file/address-space bounds. It accepts only a bounded plain tensor state_dict,
retains every key including tied aliases, rejects nonfinite values, and compares
all converted safetensors values with the loaded source before recording an
immutable conversion receipt. Source `.bin` stays outside the inference snapshot.
The runtime loader separately checks complete loading info and actual tensor
materialization. Hashes and subprocess boundaries are NOT independent attestation
or a hostile-code sandbox. This is not permission to load arbitrary pickle files.

```sh
python -m experiments.shared_stem_cell.public_smoke \
  --allow-weights-only-conversion --output /new/public-study
```

The same hosted real-weight lane opts into this explicit source conversion and
retains its logs and manifests, without uploading weights. A conversion or runtime
failure remains fatal; there is no source repair, custom-class allowlist, dummy
weights, synthetic fallback or automatic model promotion. Additional required
`hf_integration_checks` instantiate small RANDOM ModernBERT, CLIP and Whisper
models and exercise the actual pinned Transformers APIs before any public model
acquisition. Those checks are compatibility tests, not pretrained effectiveness.

### Real file-to-tower-to-connector path

`media_execution.py` consumes local SHA-bound PNG/JPEG images, 16 kHz PCM16 mono
WAV (20 ms through 30 seconds), and lists of 2..16 source frames with exact integer
microsecond timestamps. It rejects path escapes, links, changed sources,
cross-fold source/group duplication, future/reversed frame times, inconsistent
feature widths and oversized trials. Common textual instructions are allowed
across media cases; identical media or full observations may not cross folds.

The stock full CLIP and Whisper models are loaded locally under the same snapshot
and materialized-tensor checks, with every parameter frozen. CLIP text/patch tokens
are retained up to the explicit slot ceiling; video uses ordered pooled per-frame
features. Whisper uses a declared **lossy 32-time-bin mean representation**, not
an undocumented truncation or a claim of token-equivalent audio. Missing modalities
have explicit masks. The existing `controls.modality_trial` trains connectors and
all unimodal controls; predictions are sealed before holdout scoring. There is no
new training service, NDU subject, artifact selector or production owner.

Manifest schema is `hepta.shared-stem-media.v1` with `classes`, `steps`, `seed`,
`temporal`, `dataset: {path, sha256}`, and `models: {clip: <snapshot>, whisper:
<snapshot>}` (provide only needed model families). Each JSONL row has exactly
`case_id`, `group`, `split`, `scope`, `observed_at`, `inputs`, and `label`. Splits
are train/calibration/holdout/retention. An input is text, an image/audio reference
`{path,sha256}`, or a video list of `{path,sha256,timestamp_us}`. A snapshot has
`path`, immutable 40-hex `revision`, and complete filename-to-SHA256 `files`.

```sh
python -m experiments.shared_stem_cell.media_execution \
  --manifest /staged/media-manifest.json --output /new/media-study
```

Local tests use real PNG/WAV bytes and explicitly synthetic tower tensors; actual
pretrained CLIP/Whisper execution, independent media semantics, new-concept
transfer, audio/video generation and a completed six-experiment comparison are
NOT claimed. This frame-list API is not an MP4 decoder. No real model weights or
natural-media dataset were available in the local execution container.

### Actual controller-process deaths, with the browser owner surviving

`browser_recovery.py` drives the SAME private Chromium fixture from a separate
controller. Its bounded lab-only, locked, fsynced intent journal is not a product
ledger or FinalUse implementation. The controller is actually terminated after
intent/before dispatch, SIGKILLed after the browser click/before ACK, and terminated
after the terminal record. Fresh processes read the journal and only observe:
**recovery never redispatches an entered action**. Wrong browser generations remain
unknown; duplicate starts, truncated/corrupt logs and concurrent writers reject.

`wire.py` extracts the existing canonical byte helpers without changing their
bytes, avoiding Torch/NumPy initialization merely to import a controller. A fresh
`python -S` regression verifies this dependency boundary (the local environment
otherwise preloads NumPy before application code).

```sh
python -m experiments.shared_stem_cell.browser_recovery \
  --output /new/controller-crash-study
```

The locally executed three-cut study observed one not-applied and two applied
outcomes, all recovered by new controller PIDs, with zero recovery action calls
and no duplicate browser clicks. This demonstrates controller crash/reopen with a
surviving browser owner only, NOT browser death, disk power loss, host restart,
product FinalUse, arbitrary desktop competence or native/GPU speed superiority.

Local combined regression on the exact source slice: **78 tests passed**, zero
failures or skips. Earlier interrupted combined commands and the first import-guard
failure are retained in the external evidence bundle. These do not qualify the
three required hosted Transformers API checks, genuine public-weight execution,
full-repository Rust/Bazel/security checks or independent future NDU/split gains.
All six scientific/product acceptance gates remain individually evaluated.

## Continuation: public image/text tasks and post-seal learning comparisons

This continues PR #1699 from `90667585558ee5a46e43c47e7145071cef7d9d64`.
It reuses the existing execution, connector, Head and Reader owners; there is no
new production trainer, NDU subject, authority issuer or experiment-name registry.
Historical 42/78-test and browser outcomes above remain historical receipts.

### Complete existing split/System2 scoring after prediction sealing

`control_evaluation.py` consumes the existing immutable `controls.json` only AFTER
its digest is sealed. It checks exact case and arm coverage, class probabilities,
control costs and per-case stopping depth. Missing arms and changed byte streams
fail instead of becoming zero-quality or zero-cost results. The original
`execution.run` now includes these actual split/System2 comparisons in its report.
Paired gains/losses/ties are measured against continued parent and fixed recurrence;
Brier and descriptive group-mean changes are separate. Declared groups are not
certified independent samples. Confidence intervals and general FBSDE benefits
remain unavailable; equal depth ceilings do not claim equal FLOPs or wall time.

The existing modality trainer now saves same-initialization frozen predictions
and parameter identity before optimization. The media runner seals both frozen
and trained predictions, then reports their paired differences on the same
holdout/retention cases. A single-modality request previously appeared twice in
the selected-arm list, training twice and overwriting the first cost. The list
is now deduplicated before training. This correction does not certify any model
learning benefit. Media manifest mutation also fails before result publication.

### Public natural image/text execution, not a claim of independent new concepts

`public_media.py` connects the existing CLIP/connector and causal-text execution
paths to `lmms-lab/ScienceQA-IMG` public Parquet data. Model candidates are
`openai/clip-vit-base-patch32` and `Qwen/Qwen2.5-0.5B-Instruct`; names alone are
not source authority. The job resolves and seals full immutable Hub revisions
before acquisition and verifies downloaded publisher LFS/Git identities and
physical sizes. Plain checkpoint conversion remains an explicit separate opt-in;
the ordinary runtime still accepts safetensors only. The original public Stem
acquisition now also verifies publisher identities for EVERY copied member,
including tokenizer/config/safetensors, instead of merely recording its own hash.

The fixed pilot selects 64 train, 16 validation/calibration and 32 test cases.
Selection receives ONLY image, question, all ordered choices and hint. Exactly
four choices and the complete text within 64 actual CLIP tokens are required;
there is no truncation. Selection is SHA-ordered, deduplicates exact text and RGB
pixel content across folds (including differently encoded identical images), and
seals the COMPLETE cohort BEFORE its first answer lookup. Lecture/solution/answer
fields are rejected by the selector. Insufficient eligible material is a failure,
not permission to reduce the denominator or synthesize replacements. Original
image bytes are preserved. This eligibility-restricted public cohort is neither
a whole-benchmark score nor an independently reviewed natural-concept split.

The same frozen CLIP tower supplies real text/patch features to joint, text-only
and image-only connector training with frozen controls. A separate shared Qwen
Reader generates on up to 16 of those same held-out question/hint/options inputs,
using its pinned chat template. It receives NO images and is explicitly a
**text-only capacity reference**, not a multimodal Reader or NDU improvement.
Each invocation has a durable started record and unmodified raw response; the
full output seals before exact A/B/C/D scoring. Invalid outputs remain wrong,
not rewritten or dropped. Failed invocations retain their started/partial records.
This is actual causal-generation wiring, not image/audio/video generation quality
or generator consolidation. Full elapsed wall time includes acquisition; energy,
peak RSS and independent success claims remain absent unless separately observed.

```sh
python -m experiments.shared_stem_cell.public_media \
  --allow-weights-only-conversion --output /new/public-image-text-study
python -m unittest -v experiments.shared_stem_cell.test_public_media
```

The existing workflow retains its two original lanes and adds one exact-source
public image/text lane. It runs all four required stock Transformers API tests
(ModernBERT, CLIP, Whisper, causal Llama) before acquisition. Tiny random API
checks are NOT pretrained evidence. Original global/native/security checks are
unchanged. Artifacts preserve source/environment, plans, cohorts, predictions,
conversion diagnostics and failures, but never upload model weights or whole
Parquet shards. Upstream schema/model references:
- https://huggingface.co/datasets/lmms-lab/ScienceQA-IMG
- https://github.com/lupantech/ScienceQA
- https://huggingface.co/openai/clip-vit-base-patch32
- https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct

Local exact-source regression: **97 tests passed, zero failures/skips** in that
suite, including original real Chromium/controller/conversion tests and 19 new
selection/scoring tests. Python AST, workflow YAML parsing and `git diff --check`
also passed. The separate stock-HF suite was attempted but stopped at import:
`tokenizers` is missing (and Transformers is not installed). None of its four API
tests ran; that failure log is retained. Local dependency downloads also failed.
No real pretrained score, full hosted/native CI success or six-gate completion is
asserted. Genuine Laya comparison, 64..4096 target hardware, independent future
split/NDU gain, natural audio/video, multimodal generation/consolidation and product
FinalUse/host-crash recovery remain distinct work, not erased by these tests.

## Continuation: reusable Head parameters and same-model modality controls

This increment continues PR #1699 from exact source
`635efa075a2bbc6ff7e1e95e090d6a13352ad82b`. It adds no production registry,
selector, signing service, runtime owner or experiment-name matrix.

### Export the learning result, not just its predictions

`head_artifacts.py` exports the actual existing linear, gated, low-rank and
sparse-expert CPU Heads as create-only safetensors plus canonical JSON. The
existing `execution.run` now exports EACH Cell's unchanged same-initialization
Head and genuinely trained Head to `heads/<kind>/cell-<id>/<role>/`. Export and
reopen costs are separate from optimizer timing. A manifest is published only
after all weight bytes are written and synced; incomplete directories reject.
The exporter never writes an Encoder copy, arbitrary Python class or pickle.

A reopen requires BOTH the caller's external manifest SHA256 and exact binding:
Scope, logical Cell, candidate generation, Stem identity, dataset identity,
feature representation and training lineage. All tensor keys, shapes, dtype,
finite values, physical bytes and parameter digests are checked. A bounded
closed constructor creates only the existing Head type and preserves the caller's
training RNG. Loaded models are read-only for inference. Continuing learning
requires an explicit new trainable candidate copy; these artifacts deliberately
contain NO AdamW state and do not claim exact optimizer-state resume.

This is an offline candidate interchange format, NOT an alternative Artifact CAS,
independent acceptance, CURRENT selection, live revocation/final-use or production
checkpoint recovery. A product owner still must admit these bytes through its
existing selected-artifact contracts. Candidate generation 1 is an experimental
lineage label, not a self-issued Worker authority generation.

```python
from experiments.shared_stem_cell.head_artifacts import load_head

# receipt and binding come from the exact completed training report, not a
# self-described untrusted artifact. The returned model grants no authority.
head = load_head(candidate_directory, receipt["manifest_sha256"], receipt["binding"])
```

The actual local synthetic-feature study trained two Cells with four Head kinds,
exported 16 frozen/learned snapshots and reopened them in a genuinely fresh
process. All 128 probability rows matched on the same owned float32 input
materialization. A separate new-optimizer candidate changed weights while the
original in-memory and on-disk candidates stayed byte-identical. These are
mechanism results, not pretrained or independent future learning efficacy.

An initial strict replay test on directly memory-mapped feature tensors observed
maximum absolute logit difference `2.384185791015625e-7`, although the weights
were identical. Copying the exact feature bytes into the same owned Torch input
layout restored bitwise equality on this host. The first failure and diagnostic
are retained; the test does not assert universal bitwise parity across mmap
layouts, platforms, Torch versions or devices. No score-based tolerance tuning
or argmax repair is performed.

### Diagnose modality use without changing the trained Head

`controls.paired_modality_probe` evaluates the SAME joint FusionHead on unchanged
features, each modality entirely masked, and each modality cyclically reassigned
from other present examples within the SAME holdout/retention partition. Missing
modalities stay missing, singleton partitions explicitly retain identity, and
original tensors and learned parameters are unchanged. Exact donor-case mappings,
parameter identity and additional forward costs are preserved.

The existing media runner seals these probabilities together with learned/frozen
predictions BEFORE scoring. Paired gains/losses/ties are compared with the same
joint model on the observed inputs, not with a different-size model. This probes
reliance on frozen representations; it does NOT prove that a donor is semantically
contradictory, that an image is necessary to answer a question, or that causal
multimodal reasoning improved. No additional tower forward or training is hidden
in a feature intervention. Real natural-data conclusions still require completion
of the existing public image/text job and independent evaluation.

### Explicit generation-token semantics and early resource rejection

`LocalTextGenerator.generate` now preflights its entire supplied prompt batch
before the first decoder call, including exact token shape, input limits and
input-plus-continuation model context. Oversized later prompts therefore cannot
silently waste earlier decoder work. Output cardinality, prefix and token ceiling
must also match. The raw-text path preserves its normal special-token behavior;
`public_media.text_reader` explicitly uses `add_special_tokens=False` after the
checkpoint's own chat template has already formatted the input. This follows the
pinned Transformers 4.57.1 chat-template contract and records the input policy.
It prevents duplicate-special-token insertion for affected tokenizers; it is NOT
an observed Qwen accuracy gain or proof that Qwen previously inserted duplicates.
The mandatory stock causal-model API check covers the exact input token digest.

Whole-study cross-Scope checks now precede model loading, and Head artifact
binding checks precede fitting. Invalid input does not spend these expensive
operations first. Existing production resource and authorization gates are not
changed by these research preflights.

### Reproduction and exact evidence boundary

```sh
python -m unittest -v experiments.shared_stem_cell.test_head_artifacts \
  experiments.shared_stem_cell.test_modality_probe \
  experiments.shared_stem_cell.test_generation_contract
```

The final local combined suite ran **130 tests, all passed, zero skips**: 97
inherited tests plus 33 new ones. It includes actual Torch training, safetensors
read/write and fresh processes, and the inherited real Chromium/MCP/crash tests.
The SEPARATE four stock-HF API checks were attempted but blocked at import by
missing `tokenizers` (Transformers also unavailable); none is counted among the
130 passing tests. Local external DNS/download still failed. Hosted pretrained
mmBERT/Laya/CLIP/Qwen, natural audio/video, general generation/consolidation,
independent split/NDU benefit, target-host 64–4096 resources and product FinalUse
remain separate unfinished acceptance conditions. No production model is selected.

## Independent AdamW Head learning backend

The existing execution manifest may explicitly select
`head_training_backend: "grouped"`; the default remains `"scalar"`. Both train the
existing four concrete Heads, not a new model family. The grouped fitter in
`head_training.py` accepts a shared frozen feature table and per-Cell training
rows, labels, random seeds and fixed step counts. It receives no evaluation
labels. Existing Head export/reload and task scoring still apply. Grouped timings
are recorded once in the first Cell's `shared_training_report`, not duplicated as
per-Cell time. Backend identity is part of grouped artifact training lineage.

This is the existing `execution.fit` profile: replacement minibatch sampling,
mean cross-entropy per Cell, norm-1 clipping per Cell, stock AdamW with learning
rate 0.01 and zero weight decay. Losses are summed across Cells only after each
Cell mean. Parameter/moment coordinates are independent. Fixed-budget and actual
minibatch-size buckets avoid padding and remove the need to compact Adam states;
zero-step candidates never enter an optimizer. Sample-stream hashes and actual
optimizer calls, Cell updates, examples and terminal moment bytes are reported.
Parameter/feature caps are not an RSS/autograd/BLAS workspace bound. Originals
and global RNG are preserved; returned Heads are private offline candidates with
no optimizer checkpoint or selection authority. The separately reviewed
qualification branch's SGD/SwiGLU fitter has a different optimizer, sampling and
Head contract and is not silently substituted for this AdamW profile.

```sh
python -m unittest -v experiments.shared_stem_cell.test_head_training
python -m experiments.shared_stem_cell.head_training_study \
  --cells 8 --output /new/digits-8
python -m experiments.shared_stem_cell.head_training_study \
  --cells 32 --output /new/digits-32
```

The bundled-digits study requires scikit-learn 1.8.0 and uses actual public 8x8
handwritten images, not synthetic features. It records package/source data
hashes, partitions by raw pixel hash before constructing training labels, and
keeps duplicate images in one fold/Cell. Its representation is simply flattened
pixels divided by 16: **no pretrained or learned Encoder is exercised**. Both
arms use identical initial Heads, training rows, sample seeds and 80 updates per
Cell; seven repetitions alternate order and retain whole-fitting-call costs.
Parameters, sample hashes and unmodified heldout logits are compared. Predictions
are sealed before scoring; writer independence, future efficacy and full Stem
selection remain unestablished. Different Cell counts change per-Cell training
data and aggregate updates, so this is not a causal split-benefit experiment.


## Training-only routing and inheritance-matched split controls

`split_trial(..., matched_inheritance=True)` retains every original comparator and
adds `inherited_unsplit`: the same trained linear parent plus an initially-zero
nonlinear residual within the split parameter cap. Both parent and residual can
train, without expert dispatch. Split and this capacity control start at the same
parent function and use identical continuation minibatch streams; their actual
parameter gap remains visible. The fresh wider MLP still receives the full
scratch-training step budget. Shared parent training is charged once per inherited
path and never added to the scratch path. Equal steps/examples are NOT equal FLOPs,
wall time or independent efficacy. All supplied labels/shapes/routes are checked
before the first fit; the trial preserves the caller's global Torch RNG.

The existing actual-model runner uses the matched inheritance control and accepts
`split_routing: "train_two_means"`. `TrainingPartition` fits two centroids on TRAIN
features only, takes no labels, freezes its centroids, and exposes empty-child and
resource diagnostics. Every arm sees the same appended route. Default routing
remains the caller-observed Cell bit; public mmBERT smoke explicitly opts into
training-only routing. No extra Encoder call or production topology change occurs.
The post-seal evaluator requires the new arm when its comparison profile is
present and validates per-arm work, sampling hashes and parameter-cap consistency.

```sh
python -m unittest -v experiments.shared_stem_cell.test_split_learning
python -m experiments.shared_stem_cell.split_study --output /new/digits-split
```

The bundled-digit study uses the original 64 pixel/16 features (NO Encoder),
content-only train/extra-train/calibration/holdout partitioning and three fixed
seeds. Predictions and all calibration-only recommendations are sealed before
holdout labels are accessed for scoring. The simple accuracy/size recommendation
is descriptive, NOT statistical acceptance, future utility or an NDU optimizer.
Raw scores, parameter gaps, route work, optimizer-phase timings and whole-trial
spans are retained. Seeds share the same holdout, not independent task sets.
Writer-disjoint/future evidence, pretrained Stem comparisons, production split
migration and resource-adjusted longitudinal gain remain separate acceptance work.
