# Hepta shared Stem P1: executable native candidate and evidence preflight

This additive slice extends research-only shared Stem bake-off PR #2970,
stacked on shared Encoder/Cell Head PR #2695. It is
**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO** and changes no production
Worker, NDU, selected Stem, effect issuer, credential manager or durable
memory writer.

## Executable artifacts

- qa/stem-bakeoff/native_latent.py defines frozen bidirectional PyTorch
  slot Transformer architectures with **148,845,312 parameters** for the
  150M arm and **302,309,376 parameters** for the 300M arm. Default meta
  instantiation counts shapes without allocating model weights. No trained
  checkpoint or multimodal teacher knowledge is included.
- LightCellHead owns only a Gate, zero-delta low-rank Adapter,
  Task/Action/Value/uncertainty Heads. Cell state comes from the caller;
  external Memory is represented by an exact digest, not by replicated
  model weights, optimizer state, or privately written facts.
- SharedStemServer performs exactly one **Python owner-level Encoder call**
  for many independent Cell Heads. It rejects stale generation, duplicate
  Cell ids, missing Memory binding, nonfinite slots and invalid local states
  before running the shared Encoder.
- evidence_gate.py is a separate fail-closed *admission preflight*.
  The original validate_result() in #2970 checks **JSON shape only**.
  It cannot prove inference execution, and its success is not admission.
  The preflight requires source/model/checkpoint digests, source-disjoint
  train/calibration/two future/OOD splits, bounded finite metrics, all six
  measured Cell scales, actual model-forward instrumentation claims, and
  terminal blocking CI on the exact HEAD. Its strongest possible result is
  REVIEW_REQUIRED, never production authorization. Independent auditors
  must inspect original artifacts and GitHub statuses themselves.

## What has and has not been proven

The local tests run a **small random/untrained PyTorch Encoder** on CPU,
count the two full-size model architectures on the meta device, demonstrate
zero-delta head parity, and fan out one Python Encoder invocation to 64
Cell Heads. This does NOT prove one physical backend forward, trained 150M
or 300M inference, target-host latency/energy, 4096-Cell scale, multimodal
quality, memory recall, System 2 emergence, or learning superiority.

The negative evidence tests reject bogus SHA256 digests, arbitrary all-true
gate booleans, nonfinite resource metrics, reused OOD source hashes, absent
model forward hooks, stale/cancelled/pending CI, and per-Cell backbone bytes.

## Keep teacher/control arms separate

EmbeddingGemma 2 remains the short-term shared perception/Memory candidate;
the frozen existing 421M remains a cognition CONTROL, not a replicated
Cell model. T5Gemma 2 Encoder remains the long-context alternative: the
270M/270M encoder-decoder family has around 370M total parameters excluding
vision owing to shared embeddings/attention, and official model weights
require acceptance of the Gemma terms.

EmbeddingGemma 2 unifies text, image, audio and video embeddings. Selective
text-only, text+image, text+audio and full model loads are approximately
270M, 440M, 570M and 740M. Every 512/256/128-dimensional Matryoshka
truncation from 768 dimensions requires a fresh L2 normalization before
cosine similarity; different dimensions must never be compared directly.
Its pooled embeddings cannot substitute for token/slot reasoning states.

## Remaining blockers

1. Exact original-model checkpoints and accepted licenses; actually execute
   the pinned EmbeddingGemma 2 and T5Gemma 2 teacher comparisons with
   independent resource and model-forward instrumentation.
2. Train and freeze native 150M/300M students on aligned multimodal and
   long-context teacher targets. Prevent held-label leaks; preregister
   untouched future/OOD cohorts and Cell replay/calibration tests.
3. Measure one shared Encoder execution on actual target hardware, at
   1, 8, 64, 256, 1024 and 4096 active Cells, including p95/p99, memory,
   energy and Head/slot/projection/cache costs. Python owner call count is
   not sufficient.
4. Repair real repository-wide security, Bazel/cross-platform and test
   failures; require terminal exact-head blocking-ci, Architecture and
   V8 results. Queued/cancelled/skipped do not count as success.
5. Keep NO_MODEL_SELECTION / NO_FINALUSE / NO_PHYSICAL_CELL_SPLIT and
   SHADOW_ONLY / DENY_ALL until independent authority/owner review.

Local smoke: python3 -m unittest discover -s qa/stem-bakeoff -p test_*.py -v

## P2 multimodal slot differentiation + offline distillation

- `qa/stem-bakeoff/multimodal_bridge.py` adds a **shared**, trainable per-modality
  projector and cross-attention latent slotizer with an explicit missing mask,
  bounded token budgets, time tags for audio/video/UI events, generation and
  SHA256-shaped source references. It accepts precomputed features only and
  never fetches teacher weights or allocates per-Cell modality towers.
- An EmbeddingGemma 2 pooled output is **one** source token, not proof of image
  regions or temporal reasoning. T5Gemma 2 hidden states and specialist tower
  tokens need real, pinned and independently audited producer receipts.
- `shadow_distill_step` supports a small, *offline* trainable student using
  MSE/cosine alignment against detached teacher features. Neither synthetic
  toy-step improvements nor caller-provided SHA strings prove pretrained
  knowledge, modality utility, provenance, future/OOD gains or production use.
- Tests check real tiny CPU forward/backprop, Gate/Head separation, temporal
  ordering, missing-mask provenance, invalid inputs, and detached teacher
  targets. The shipped 150M/300M variants remain **untrained blueprints**.


## P3: local-only teacher checkpoint and multimodal forward probes

This slice adds teacher_snapshot.py and teacher_forward.py plus adversarial
tests. It creates offline-capable real-model execution paths, NOT
an achieved pretrained-model qualification, dataset result, or promotion.

| Candidate | Model origin | Current path | Still missing |
| --- | --- | --- | --- |
| control_421m | Existing Hepta model | Leave unchanged as cognition control | Exact control artifact and common comparison |
| embeddinggemma2_740m | google/embeddinggemma-2 | AutoProcessor plus AutoModel; local text/image/audio/video mixed batches | Accepted and independently attested weights, representative data, target-host profiling |
| t5gemma2_encoder_270m | google/t5gemma-2-270m-270m | AutoModelForSeq2SeqLM.get_encoder, text-only first | Real model, vision and long context, encoder-only resident memory |
| hepta_latent_150m/300m | Native prototype | Frozen PyTorch encoder and synthetic offline training seam | Teacher-aligned checkpoint, quality and hardware evidence |

Important: the T5 probe loads an encoder-decoder checkpoint before
taking its Encoder handle; this is NOT an encoder-only resident footprint.
The EmbeddingGemma probe loads the full multimodal checkpoint even for
text-only inputs; selective tower loading is a separate memory-optimization
milestone, not an achieved benchmark.

### Checkpoint custody

teacher_snapshot.py hashes every regular checkpoint file and requires:
a 40-hex immutable source revision, externally pinned 64-hex inventory
SHA256, expected model_type, safetensors weights and a positive operator
license-acceptance declaration. It rejects symlinks, absent checkpoints,
changed files, wrong models and malformed revisions. HF cache symlinks
must be materialized into an actual offline directory before validation.
Hash agreement only checks **operator-pinned local bytes**. It does not
independently verify publisher identity, model pretraining, legal access,
or capability. A digest computed from the same untrusted mutable
directory is not independent attestation.

The checkpoint must already be available from an independently approved
license/access workflow. No weights, credentials or network access are
embedded into this PR. Pin the inventory digest and original model
revision in an independent external source ledger before running.

### Local use (after checkpoint pinning)

~~~sh
python3 qa/stem-bakeoff/teacher_snapshot.py \
  --snapshot /mnt/hepta/checkpoints/embeddinggemma2 \
  --candidate embeddinggemma2_740m \
  --revision "$PINNED_UPSTREAM_SHA40" \
  --expected-inventory-sha256 "$EXTERNALLY_PINNED_INVENTORY_SHA256" \
  --operator-accepted-terms
~~~

Example local records.json, with media paths relative to media-root:

~~~json
[
  {"text": "An operator requests a GUI action"},
  {"text": "Describe the UI", "image": "ui/frame_001.png"},
  {"audio": "audio/segment_001.wav"}
]
~~~

~~~sh
python3 qa/stem-bakeoff/teacher_forward.py \
  --candidate embeddinggemma2_740m \
  --snapshot /mnt/hepta/checkpoints/embeddinggemma2 \
  --media-root /mnt/hepta/approved-media \
  --records-json /mnt/hepta/approved-media/records.json \
  --revision "$PINNED_UPSTREAM_SHA40" \
  --expected-inventory-sha256 "$EXTERNALLY_PINNED_INVENTORY_SHA256" \
  --operator-accepted-terms --device cpu --truncate-dim 256
~~~

T5 uses its own checkpoint, the t5gemma2_encoder_270m candidate,
text-only records and no truncate-dim. These two models do NOT share a
numerically interchangeable vector space without a learned bridge.

The probes require separately version-pinned, locally installed
Transformers, Torch and any required media decoders. They explicitly
disable Hugging Face network fetch and remote code, use CPU FP32 or
CUDA BF16, mask-aware float32 pooling and Matryoshka prefix
re-normalization. A PyTorch model-level hook counts MODULE forwards;
it is not an independently observed physical kernel count. One elapsed
wall-clock sample cannot qualify p95/p99, memory or energy, and source
SHA declarations cannot establish source authentication.

### New negative tests and still-open blockers

test_teacher_snapshot.py checks pin drift, symlink rejection, model
identity, missing weights and operator terms. test_teacher_forward.py
checks local media paths, changing source bytes, unsupported T5 modes,
strict modality/shape bounds, masks, nonfinite features and 256D prefix
normalization. Dedicated CI runs stdlib checks independently of pinned
CPU Torch tests, without downloading any model checkpoint.

Still blocked: authorized independently attested original weights;
genuine multimodal and context forward evidence; independently held
future/OOD Cell data and calibration; encoder-only T5 export; trained
150M/300M students; physical hardware 1/8/64/256/1024/4096-Cell
p95/p99, peak memory, energy and true model-forward instrument;
complete exact-HEAD cargo-deny, Architecture, V8 and cross-platform Bazel
security/test gates; independent owner and permission acceptance.
All new paths remain SHADOW_ONLY / DENY_ALL / HOLD_NO_GO and never
select a production Stem, mutate external Memory or issue Cell actions.


## P4: executable six-scale *synthetic* Cell fan-out and receipt robustness

`qa/stem-bakeoff/scale_probe.py` runs a real **tiny random** 32-dimensional,
one-layer frozen PyTorch Encoder and the actual `LightCellHead` /
`SharedStemServer` implementation at **1, 8, 64, 256, 1024 and 4096**
active Cells. It measures the shared module-forward hook delta and owner call
delta for each request batch. An exact-head Linux shadow CI job executes the
six-scale probe and asserts both counts equal the number of sampled batches.
It also records per-Cell Head parameters, response-time samples/p50/p95/p99
and the Linux **process-lifetime** peak RSS. No per-Cell Encoder is constructed
by the probe.

Run offline, without checkpoint downloads:

~~~sh
python3 -m unittest discover -s qa/stem-bakeoff -p 'test_scale_probe.py' -v
python3 qa/stem-bakeoff/scale_probe.py --repeats 2
~~~

The CLI refuses duplicate, unsorted or unregistered Cell scales, invalid
repeat counts and malformed seeds. The receipt hard-codes
`may_satisfy_real_model_bakeoff_gate=false`,
`model_pretrained=false`, `physical_gpu_kernel_count_attested=false`,
`energy_measured=false`, `production_activation_allowed=false` and
`SHADOW_ONLY/DENY_ALL/HOLD_NO_GO`. This probe deliberately cannot generate a
`REAL_MODEL_OBSERVED` result for `evidence_gate.py`.

**Interpretation is strictly bounded:** a random tiny Encoder does not
measure 421M control, EmbeddingGemma 2, T5Gemma 2 or 150M/300M trained
students. Two timing samples are a CI diagnostic, not statistically meaningful
p99. A PyTorch module forward hook is not GPU kernel instrumentation. The
process-lifetime high-water RSS can include unrelated allocations and is not
a per-batch GPU peak. Model download/license, held-out datasets, future/OOD
quality, independent evidence, energy and true target-hardware benchmark
blockers remain open.

`stem_bakeoff.py` and `evidence_gate.py` now also return structured
fail-closed errors for malformed JSON root objects and non-array Cell
components, rather than allowing unexpected Python type errors to interrupt
the receipt assessment. No malformed receipt gains authority.


### P4 checkpoint-custody regression fix

The local snapshot inventory now rejects hardlinked regular files, not just
symlinks. Otherwise a supposedly isolated checkpoint can alias a writable
file outside its snapshot directory. After computing and comparing the
independently pinned inventory digest, the verifier also rehashes bounded
`config.json` bytes immediately before parsing `model_type`; a file swap
between the inventory and parser is rejected. Both conditions have negative
unit tests.

These checks improve the local byte-custody boundary only. They do **not**
make a mutable filesystem inherently immutable, prove upstream publisher
identity, or replace a read-only mount/content-addressed verified
materialization followed by independent source attestation.


## P5: pinned teacher-to-student feature-shard boundary (offline only)

The existing teacher forward emitted a digest of its pooled features but no
readable tensor for `shadow_distill_step`. The optional
`--feature-output-dir /mnt/hepta/private-feature-shards/unique-run-name`
argument now records **the actual output of a successful local teacher
forward** as a bounded float32 NumPy `features.npy` and canonical
`manifest.json`, using `qa/stem-bakeoff/feature_shard.py`. The output
directory must be previously absent, under an existing owner-controlled
parent **outside the repository checkout**, with 0700 directory and 0600
file permissions. It will not download weights or export to Git.

~~~sh
python3 qa/stem-bakeoff/teacher_forward.py \
  --candidate embeddinggemma2_740m \
  --snapshot /mnt/hepta/checkpoints/embeddinggemma2 \
  --media-root /mnt/hepta/approved-media \
  --records-json /mnt/hepta/approved-media/records.json \
  --revision "$PINNED_UPSTREAM_SHA40" \
  --expected-inventory-sha256 "$EXTERNALLY_PINNED_INVENTORY_SHA256" \
  --operator-accepted-terms --device cpu --truncate-dim 256 \
  --feature-output-dir /mnt/hepta/private-feature-shards/unique-run-name
~~~

The shard manifest binds:
model candidate/revision; operator-pinned checkpoint inventory SHA256;
ordered source-manifest SHA256; feature shape and dtype; digest of raw
float32 tensor and of serialized NPY. It stores no raw text, media or
credentials. `read_shard(directory)` loads NPY with `allow_pickle=False`,
validates the exact schema/size/finite shape/digests, rejects symlink and
hardlink aliases, and returns the tensor plus non-authorizing manifest.
Tests verify roundtrip and tamper, bad revisions, symlink and repository-path
rejections. Pretrained weights, real model quality and independent source
provenance are **not** attested by this data container. A digest supplied by
the same operator is not an independent witness.

The teacher forward is still **read-only**, never updates a Cell or source
Memory. A later offline trainer may explicitly read these shards and pass
tensor targets to `shadow_distill_step`, but the shard does **not**
prove teacher/model performance or run any native 150M/300M training.
Holdouts, license review, independently attested original checkpoint bytes,
target-hardware profiling and terminal exact-head CI remain blockers.
All receipts retain `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`; no model is selected
or promoted through this interface.
