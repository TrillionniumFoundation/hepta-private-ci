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
