# Neuron Stem Qualification — shadow only

This directory contains executable research tools for three planned comparisons:
(1) four frozen encoder backbones, (2) four feature representations and six
low-parameter Head architectures, and (3) 64/256/1024/4096-cell scaling.

No script here can select production artifacts. The tests run without network
access or downloaded pretrained weights, and do not establish model accuracy.

**P0 artifact integrity (shadow-only):** Real Jina trials now require an exact
local Hugging Face cache snapshot under
`models--jinaai--REPO/snapshots/<FULL40SHA>` and a **separately
precommitted SHA256 census** of its model weights, actual task Adapter,
Tokenizer, custom Python code and all other snapshot files. Revision SHA
alone is insufficient to attest what the local runtime loaded. Real trial
execution never downloads weights. The snapshot is checked before and
after loading remote model code, and its observed file-census digest is
included in the Stem feature manifest and every real experiment report.
Model-free offline fixtures remain explicitly unattested.

## Data

Input JSONL rows must contain case_id, group_id, scope_id, task_id, split,
language, state, question, options, label and event_time. The required splits
are train, calibration, test, future, ood. Group and exact-content leakage are
rejected, and future events must follow the earlier windows.

## Commands

First generate the plan and audit the dataset:

    python3 qualification/neuron-stem/qualified_eval.py matrix --models qualification/neuron-stem/models.json --out matrix.json
    python3 qualification/neuron-stem/qualified_eval.py audit --dataset TASK.jsonl --out audit.json

Train one task-specific Head from a frozen, SHA-pinned real HF Encoder:

    python3 qualification/neuron-stem/hf_trial.py --model mmbert-small --revision FULL40HEXSHA --task-id decision-v1 --dataset TASK.jsonl --mode joint --head film --budget 2048 --shots 32 --steps 100 --output candidate.jsonl

Assess predictions against independently collected no-change predictions:

    python3 qualification/neuron-stem/qualified_eval.py score --dataset TASK.jsonl --baseline no-change.jsonl --candidate candidate.jsonl --out comparison.json

Probe an actual HF inference backend (not the Hepta production worker):

    python3 qualification/neuron-stem/scale_probe.py --model mmbert-small --revision FULL40HEXSHA --dataset TASK.jsonl --mode joint --cells 1024 --active-fraction 0.25 --repeat-fraction 0.5 --similarity medium --requests 256 --batch-size 8 --db /tmp/stem-scale.db --output /tmp/stem-scale.jsonl

## Evidence limitations

Production teacher predictions for Laya 421M / Laya Multilingual 322M,
task outcome evidence, signed NDU receipts and data permissions must be
provided independently. Jina's optional remote model code requires an
explicit, pinned, reviewed opt-in. Encoder revisions must be full commit SHAs.

The scale probe genuinely executes batched frozen Encoder forwards and
independent Cell Heads, and measures SQLite WAL clean-reopen consistency.
It does not measure production worker queues or verified crash recovery.
A first warm forward is not a cold-load observation; model load time is
reported separately. CPU/RSS data are valid only on the measured host.

Never treat reported utility IDs or measurement labels as cryptographically
verified receipts. All results remain shadow-only. Independent Evaluator,
Selector and Executor promotion boundaries remain unchanged.

Run offline tests:

    PYTHONPATH=qualification/neuron-stem python3 -m unittest discover -s qualification/neuron-stem -p 'test_*.py' -v


## Jina v5: shadow-only follow-on (stacked qualification)

The Jina v5 Text Nano/Small and Omni Nano/Small profiles are registered under
`models.json:jina_v5_models`; they are **not** fed to the older
`hf_trial.py` AutoModel/mean-pooling path, which would produce incompatible
task embeddings. Instead, `jina_v5.py` uses Jina's official, task-adapter-aware
`SentenceTransformer.encode_query/encode_document` methods, verifies the full
768/1024-dimensional output, and L2-normalizes supported Matryoshka slices.
It never silently falls back to pooled raw hidden states or to an unpinned model.
Everything requires a full 40-character Hugging Face revision SHA.

All model weights and external model code must be approved and staged on the
target host. By default no download is allowed, and executing remote model
code requires the explicit `--allow-pinned-remote-code` opt-in. Do not review
`main` once and assume a later revision is the same code. The project is
non-commercial, but Jina weights retain their independent CC BY-NC 4.0 notice.

### Genuine learned-Head trial

Example with **preexisting, licensed task JSONL**, a reviewed revision, and
installed dependencies (`torch`, `transformers`, `peft`,
`sentence-transformers`, `psutil`, and Jina's pinned model dependencies):

```sh
python3 qualification/neuron-stem/jina_v5_trial.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --store-root /approved/hf/models--jinaai--jina-embeddings-v5-text-nano \
  --snapshot /approved/hf/models--jinaai--jina-embeddings-v5-text-nano/snapshots/FULL40CHARMODELCOMMITSHA \
  --expected-snapshot-digest INDEPENDENTLY_APPROVED_CENSUS_SHA256 \
  --task-id decision-v1 --dataset /approved/decision.jsonl \
  --principal-id local-researcher --head linear --budget 16384 \
  --dimension 256 --representation joint --shots 32 --steps 100 \
  --allow-pinned-remote-code --output /evidence/nano-predictions.jsonl
```

The trial trains **only the Cell Head**: shared trainable projection count = 0
because native Jina Matryoshka truncation provides 256/512-dimensional features.
The inputs are also checked and roundtripped through bounded, nearest-even
signed Q24 before training and evaluation. A companion
`candidate.jsonl.frozen-head.jsonl` (where candidate is the chosen output
filename) records the **same-initialization frozen Head** ablation; it is not
the actual no-change production baseline.
This avoids hiding an independently learned per-Cell projection's cost. A
separate frozen-Head/no-change prediction file MUST be provided before quality
claims; a new Head trained on test/future labels is invalid. Task labels are
used for training only in `train` and for temperature selection only in
`calibration`. All representations are genuine Jina sentence-level embeddings;
this does not implement landmark tokens or learned cross-attention.

Compare independently produced paired predictions:

```sh
python3 qualification/neuron-stem/statistical_gate.py \
  --dataset /approved/decision.jsonl \
  --baseline /evidence/no-change.jsonl \
  --candidate /evidence/nano-predictions.jsonl \
  --frozen-head /evidence/nano-predictions.jsonl.frozen-head.jsonl \
  --task-id decision-v1 \
  --min-future-groups 30 --bootstrap-replicates 2000 \
  --output /evidence/nano-offline-quality-gate.json
```

The bootstrap resamples **source groups**, not individual correlated events,
and requires the 95% confidence lower bound on accuracy gain > 0 and the
upper bound on Brier delta < 0, without task-level regressions above the
precommitted tolerance. The separate `cell_learning_gate_passed` flag
requires this to hold **both** against the real no-change baseline **and**
against the same-encoder, same-initialization frozen Head. Omitting the latter
cannot prove actual Cell learning. Even a passing offline quality gate is advisory only:
`production_promotion_permitted` and NDU signature verification remain false.

### Multimodal shadow pairing

Provide a separately held-out JSONL, with unique `case_id`, `scope_id`,
`group_id`, `split` (test/future/ood), `modality` (image/audio/video),
relative `path`, `media_sha256`, `paired_text`, and timezone-aware ISO-8601
`event_time`. The future window must strictly follow test and identical
media digests cannot leak across windows. All media is local,
contained within `--media-root`, has a frozen digest, and is not copied to the
report. At least two unique positive texts must exist in each retrieval cohort.

```sh
python3 qualification/neuron-stem/jina_v5_multimodal.py \
  --text-model jina-v5-text-nano --text-revision TEXT40CHARCOMMITSHA \
  --text-store-root /approved/hf/models--jinaai--jina-embeddings-v5-text-nano \
  --text-snapshot /approved/hf/models--jinaai--jina-embeddings-v5-text-nano/snapshots/TEXT40CHARCOMMITSHA \
  --text-snapshot-digest APPROVED_TEXT_CENSUS_SHA256 \
  --omni-model jina-v5-omni-nano --omni-revision OMNI40CHARCOMMITSHA \
  --omni-store-root /approved/hf/models--jinaai--jina-embeddings-v5-omni-nano \
  --omni-snapshot /approved/hf/models--jinaai--jina-embeddings-v5-omni-nano/snapshots/OMNI40CHARCOMMITSHA \
  --omni-snapshot-digest APPROVED_OMNI_CENSUS_SHA256 \
  --modality vision --dimension 256 --direction media-to-text \
  --dataset /approved/paired-media.jsonl --media-root /approved/media \
  --principal-id local-researcher --allow-pinned-remote-code \
  --output /evidence/paired-alignment.json
```

The retrieval direction is a frozen part of experiment identity:
`media-to-text` uses the Omni media **query** adapter and the paired text
**document** adapter, whereas `text-to-media` uses text **query** and Omni
media **document**. Never use document/document cosine to claim official
asymmetric Jina retrieval accuracy, and never aggregate the two directional
Recall@1 scores without distinguishing their query/document contracts.

This measures retrieval-alignment only. Object relation and video temporal
reasoning require separately approved labels and fusion experiments, not
merely text/Omni vector cosine.

### Measured research batch/WAL probe

```sh
python3 qualification/neuron-stem/jina_v5_scale_probe.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --store-root /approved/hf/models--jinaai--jina-embeddings-v5-text-nano \
  --snapshot /approved/hf/models--jinaai--jina-embeddings-v5-text-nano/snapshots/FULL40CHARMODELCOMMITSHA \
  --expected-snapshot-digest INDEPENDENTLY_APPROVED_CENSUS_SHA256 \
  --dataset /approved/decision.jsonl --principal-id local-researcher \
  --cells 1024 --active-fraction .25 --repeat-fraction .5 \
  --round-robin --requests 4096 --batch-size 8 --dimension 256 \
  --allow-pinned-remote-code --db /evidence/scale-wal.db \
  --output /evidence/scale-trace.jsonl
```

The scale probe records measured research-encoder batch calls, active Head
count, actual tick coverage, group-committed SQLite WAL costs, full-batch
latency, process CPU/RSS, and a clean-reopen invariant. Heads here are
**random initialized**; this is a resource probe, not a learning test.
The resource probe includes strict Q24 feature conversion, and a separate
research-only Q24 feature digest must never be mistaken for a signed Rust
`NeuronFeatureReceiptV1`.
Neither the probe nor its output is a Rust production worker receipt,
authenticated NDU result or unclean-crash recovery qualification. The 4096
Cell case is valid only with explicit actual coverage reporting.

### Offline tests and mandatory evidence boundaries

```sh
python3 -m compileall -q qualification/neuron-stem
PYTHONPATH=qualification/neuron-stem python3 -m unittest discover \
  -s qualification/neuron-stem -p 'test_*.py' -v
```

The offline CI intentionally does not download 239M–1.74B weights or
fabricate learning, CPU/RSS, GPU or future-NDU measurements. To qualify
production, independent operators still need signed artifact/CAS, complete
inference-control worker and scheduler evidence, real target-host resources,
unclean crash/ack-loss replay, future windows, real utility receipts, and
Executor/Selector separation. All existing and new scripts fail closed with
zero authority to change a selected model or active Cell generation.

### Continual per-Cell test-then-learn and retention

Supply approved chronological data with **all existing evaluator columns** plus
a stable `cell_id` per row. The prequential runner uses exactly one frozen
Text Nano/Small Stem; initializes bounded distinct Cell-local Heads, trains only
from the `train` partition, freezes same-initialization Heads, and replays
`future` events in UTC order. It hashes the prediction **before** reading the
event label for a bounded update, then separately tests retention on untouched
historical `test` cases. The historical test labels are never used for a
gradient; resulting retention diagnostics do not authorize model selection.

```sh
python3 qualification/neuron-stem/prequential_trial.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --store-root /approved/hf/models--jinaai--jina-embeddings-v5-text-nano \
  --snapshot /approved/hf/models--jinaai--jina-embeddings-v5-text-nano/snapshots/FULL40CHARMODELCOMMITSHA \
  --expected-snapshot-digest INDEPENDENTLY_APPROVED_CENSUS_SHA256 \
  --dataset /approved/prequential-cell-events.jsonl \
  --task-id decision-v1 --principal-id local-researcher \
  --dimension 256 --head film --budget 16384 \
  --pretrain-steps 4 --update-steps 1 \
  --max-cells 4096 --max-total-head-parameters 100000000 \
  --max-future-events 50000 --max-retention-brier-regression .01 \
  --allow-pinned-remote-code --output /evidence/continual-shadow.json
```

The complete event replay is an **offline** test-before-learn experiment.
No signed live outcome, production online learning, inference permission,
correctness of remote model adapters or NDU causality is inferred from it.
The model/Head digests, Q24 input conversion, trained and frozen outcomes,
per-Cell retention, updates, RSS and explicit approximation limits are retained
in the result.

### Independent research resource budget

Compare the exact same measured research workload for two *distinct* Jina Stems
(Nano versus Small), with matching input digest, active Head count, batch,
Cell/Head dimensions, random seed and observed machine/dependency environment.
Create a separate, precommitted budget JSON file (values below are **field
names only**, not suggested host targets):

```json
{
  "schema": "hepta.neuron-research-resource-budget.v1",
  "signed_production_budget": false,
  "max_peak_rss_bytes": 0,
  "max_request_p99_ms": 0,
  "min_throughput_rps": 0,
  "max_cpu_seconds_ratio": 0
}
```

Replace every zero with an externally approved **positive** budget; zero
is intentionally rejected. Then execute:

```sh
python3 qualification/neuron-stem/resource_gate.py \
  --reference /evidence/nano-scale.jsonl.summary.json \
  --candidate /evidence/small-scale.jsonl.summary.json \
  --budget /approved/research-budget.json \
  --out /evidence/paired-resource-budget.json
```

No 'same physical host' cryptographic attestation is manufactured from
environment equality, and research batch latency cannot prove production
Rust scheduler microbatch, NDU or crash-recovery qualification.


### Additive Rust inference contract: Scoped Stem feature binding

`codex-rs/hepta-infer-core/src/stem_feature_binding.rs` provides
`StemFeatureRefV1`, `StemAccessContextV1`, `StemHeadBindingV1`,
`stem_feature_vector_digest_v1`, and `bind_stem_feature_request_v1`.
This pure function binds the exact ≤512-width, bounded, signed-Q24 feature
vector into the existing `NeuronFeatureRequestV1` only after checking
Scope, Principal, Generation, Authority Epoch, nonexpired lease, revocation
flag, exact vector digest, and Head compatibility with the *selected*
Stem model/generation/feature projection. The Neuron request's encoder digest
is an exact versioned **pipeline digest**, derived from Stem model ID and
generation, weights, tokenizer, preprocessor, Matryoshka projection, and
feature width — it is not merely a hash of backbone weights. Rust and Python
pin the 2-dimensional golden fixture pipeline digest
`67d4c68e2092bcde7fdccca0386fb39442deac2a0ecb8ff8d98a5510067f5504`.
Reuse across Cell Heads is possible
only under the same checked source identity.

Python `q24_bridge.rust_stem_feature_vector_digest_v1` follows the same
digest domain and byte order as Rust. Both embed the golden vector:
`[0.5, -0.25] -> 148ae0b91ab97729f72d745e989ac7b03614438cc6030edb2f79748049c70b59`.

**Security boundary:** the Rust access input is still a caller-supplied
claim. This module does not authenticate it, issue a grant, sign a result,
open an artifact, dispatch inference, checkpoint CAS, or change a selected
generation. The production inference.control owner MUST independently
authenticate the Scope/Principal, selected bundle, current grant, revocation
and final-use authority before dispatch. All constructed requests have
`DENY_ALL` authority until independent product gates complete. Rust unit
tests require a toolchain and CI; neither has been independently confirmed
green for this new source.

### Durable pre-label learning evidence

The prequential shadow runner additionally writes an *exclusive-create*
`output.prediction-journal.jsonl` before reading each future label.
Each label-free record includes event order, input/Head digests, probabilities
and exact SHA256; it is flushed and `fsync`ed before the corresponding
head update. The result manifest binds the journal digest and count. This
is only write-ahead **research evidence** (not a signed independent evaluator
or atomic production checkpoint). A partial journal from a failed run cannot
be overwritten by retry under the same output path.

### Final no-change-first main review report

Use `review_report.py` for the single final review matrix. It enumerates
**every** registered model and preserves No-change as the first retained
baseline, even when all experimental evidence is missing. A real candidate
requires a future-window `statistical_gate.py` receipt with the same-encoder
frozen-Head control; a resource result requires an exact paired
`resource_gate.py` receipt for that same revision. Only a full 4096 logical
Cell resource cohort may populate the 4096-cell throughput column.

Create `/approved/stem-review-input.json` such as:

```json
{
  "schema": "hepta.neuron-stem-review-input.v1",
  "candidates": [
    {
      "model_id": "jina-v5-text-nano",
      "quality_receipt": "nano-offline-quality-gate.json",
      "resource_receipt": "nano-paired-resource-budget.json"
    }
  ]
}
```

All paths are resolved **relative to the manifest location** and must refer
to actual files; an absent optional model remains `待测`, while a named
missing/mismatched/unpinned file is a hard error. Run:

```sh
python3 qualification/neuron-stem/review_report.py \
  --models qualification/neuron-stem/models.json \
  --manifest /approved/stem-review-input.json \
  --out /evidence/stem-review.json
```

This writes a companion `stem-review.md` with the requested future gain,
negative transfer, measured peak RSS, research p99 and **only if truly
measured** 4096 Cell throughput. It labels offline classifier gains
separately from **unproven causal NDU**. The report is not a signed source
verification, does not approve the research budget, and unconditionally
denies production promotion. Separate independent signature validation,
signed real NDU, real production Worker, crash recovery and final-use gate
remain mandatory.


## Experiment C: prequential + genuine no-change three-way review

prequential_threeway_review.py is a **consumer of the existing
prequential_trial.py journal, qualified_eval dataset, and resource_gate.py
paired research receipts**, not a new trainer, worker or authority owner.

It joins a chronological two-window, test-then-learn output with an
**externally captured** production no-change prediction stream. The required
future source rows carry an extra preregistered future_window field
(future_1 or future_2); train/calibration/test/future/ood split semantics
remain unchanged. The matched frozen Head is the existing post-historical-
pretrain, same-initialization copy. The reporter checks that the first
prediction of each Cell agrees with that frozen copy *before* any future
learning, and that all subsequent trained logits match an exact fsynced,
label-free prediction precommit record and input/Head digest.

The no-change JSONL includes case_id, scope_id, model_id=no-change,
status=Succeeded, immutable model_revision (40 hex), weights_digest,
generation, dataset_digest, input_digest and probabilities (in the
registered option order). It must be produced **outside the candidate
trainer** by the current canonical serving/evaluation owner. An inline
JSON field that claims authentication cannot grant independence.
This offline script checks identity and complete exact paired coverage
but cannot itself verify the owner signature or live revocation.

Run only after authentic pretrained weights and approved data exist:

    python3 qualification/neuron-stem/prequential_threeway_review.py \
      --dataset /approved/episodes.jsonl \
      --trial /scratch/actual-prequential.json \
      --prelabel-journal /scratch/actual-prequential.json.prediction-journal.jsonl \
      --no-change /approved/frozen-production-nochange.jsonl \
      --resources /scratch/four-paired-scale-gates.json \
      --output /scratch/threeway-offline-review.json

The optional --resources JSON array must contain the **four separately
measured** paired resource gate results at 64/256/1024/4096 logical Cells,
all including actual active and distinct ticked Cell counts and matching
model revision. Resource reporting needs true Jina execution on the named
research hardware; mock or fabricated summaries cannot count. The script
requires both future windows to show Bonferroni-corrected grouped gains
against *both* the frozen Head and production no-change, respects per-Cell
historical Brier retention caps, and refuses missing or mismatched evidence.

Outputs are always offline-only, unsigned research diagnostics with
production_promotion_permitted=false. Even a pass is NOT independent NDU,
a real native shared Encoder, a production final-use grant, a physical 4096
Cell throughput measurement, unclean WAL recovery, or a release decision.


### Frozen-Head evidence is immutable across all future events

The prequential runner now places frozen_control_head_digest and
frozen_control_probabilities into the fsynced, label-free prediction journal
BEFORE revealing a future event label. The same frozen weights digest must
equal the post-historical-pretrain initial_head_digests entry for each
Cell/event. Its final frozen_final_head_digests must exactly equal the same
initial snapshot, including dormant historical-only Cells.

The offline prequential_threeway_review.py verifies the sealed record,
actual per-event frozen-Head identity/probabilities and final frozen Head
inventory; it rejects a freshly rehashed journal with substituted control
predictions. This validates a *self-reported local research execution trace*,
not a signed independent evaluator receipt or proof that a malicious trial
executor never read a label beforehand. Production learning and promotion
remain blocked until independently authenticated sources and NDU outcomes.


### C: per-future-window calibration and the remaining OOD gap

The existing prequential_threeway_review.py now includes separately
descriptive 15-bin ECE, normalized multiclass Brier and accuracy for
**no-change**, **frozen matched Head** and **learned Cell Head** in
future_1 and future_2. They use exactly the same paired event IDs, option
order and offline future labels; calibration is descriptive and does NOT
adjust a candidate's temperature or other parameters using future labels.

The prequential replay does **not** emit the three matched OOD decision
streams with an independently calibrated acceptance threshold. Therefore
the offline report explicitly sets ood_threeway_model_evidence_present=false
and full_quality_and_ood_gate_passed=false, even if the future predictive
gain precheck passes. An offline ECE value, even with paired bootstrap,
cannot substitute for real OOD false-acceptance evidence, external NDU
outcome signatures or production model promotion authorization.


### Fail-closed JSON evidence decoding

The existing qualified_eval.read_jsonl reader and the C three-way
prequential journal now use the same strict decoder: duplicate object keys,
NaN/Infinity extensions, empty physical rows, and non-object JSONL records
are rejected. This covers dataset labels, ordered options, externally
supplied no-change predictions, post-training trial evidence, and frozen
pre-label prediction journals. A new test specifically rehashes a journal
with two case_id fields that Python's default json.loads otherwise resolves
silently to the last value. The immutable journal byte SHA alone is not
sufficient to prohibit ambiguous physical input. This change is a research
integrity requirement and adds no cryptographic signatures, independent
NDU permissions or production capability.


### Immutable three-way review output

The prequential_threeway_review.py CLI now writes its evaluation report with
exclusive-create file semantics. It refuses to overwrite a prior report,
including a prior non-authorizing diagnostic whose no-change or frozen
results differ. Nonfinite/invalid JSON serialization is rejected before a
file is created. Source-run prediction journals and output reports remain
operator-supplied or local unsigned evidence; exclusive-create protects
audit history but is not CAS, a signed evaluator receipt, durable crash
transaction, or a production final-use grant.


### Optional matched three-arm post-future OOD diagnostic

`prequential_threeway_review.py --ood-receipts PATH.jsonl` consumes a fully
paired external prediction trace for historical `calibration` and OOD cases
from three actual sources: production `no_change`, post-history frozen Head,
and the continuously learned Cell Head. Each row must be label-free and bind
its sample ID, Scope, Cell, exact state/question/**ordered** options hash,
case time/split, model revision, Head/weight digest and (for no-change) the
same original model generation as the future baseline. The OOD cohort must
occur strictly **after** the two future learning windows. The learned
calibration predictions must equal the frozen same-initialization baseline;
the learned OOD Head must match each Cell's final update-chain digest.

For each of three arms the reviewer freezes the 5th-percentile confidence
threshold on historical ID calibration predictions *before* evaluating OOD
labels, then reports historical acceptance, OOD false acceptance, paired
candidate-vs-frozen/no-change FAR deltas and possible negative transfer.
Missing cases, duplicates, altered Scope/options, swapped weights, drifted
no-change generation, embedded labels or an alleged signed evaluation
result fail closed.

This is strictly an **unsigned offline descriptive diagnostic**, even if
complete paired predictions are supplied. The scorecard's
`ood_threeway_model_evidence_present`, `full_quality_and_ood_gate_passed`
and `production_promotion_permitted` stay `false` until independently
authenticated prediction producers, signed NDU/outcome receipts, verified
actual model inference, native Worker admission and target hardware
acceptance are implemented by the respective production owners.
`prequential_trial.py` does NOT fabricate the external no-change arm.


### Real frozen/learned model-produced OOD sidecar (no no-change impersonation)

On a *genuine* pinned Jina v5 local-weight `prequential_trial.py` run,
`--emit-ood-model-receipts` can now emit two and **only two** per-Cell model
prediction arms to `<output>.ood-model-receipts.jsonl`. Before any future
label update, it snapshots learned/frozen historical-calibration predictions
and exact initial Head weight digests. After both future learning windows, it
runs the actually loaded Jina Encoder and the final learned/frozen Heads on
the OOD input cohort, requires OOD to occur later than every future event,
and binds the final per-Cell digest without using OOD labels. The sidecar
is created exclusively, flushed and fsynced; its byte SHA is recorded in
the shadow trial. The output explicitly records
`production_no_change_ood_receipts_present=false`.

The independent production no-change owner must separately emit its own
calibration/OOD predictions with the same immutable revision, weights and
generation as the future baseline. Combine only after auditing all producer
and dataset identities, then provide the full three-arm JSONL to
`prequential_threeway_review.py --ood-receipts`.

Synthetic tests check the output contract, NOT pretrained model learning.
No automatic completion of the no-change arm, independent signature
verification, production authorization, artifact CAS or release occurs.


### Operating-system availability is a production security boundary

The current `codex-hepta-prompt-registry` durable Owner implements verified
private 0700 directory permissions, no-follow handle-relative file opens and
durability semantics **only for Unix**. Non-Unix callers explicitly return
`UnsafeStateDirectory` *before creating any state*. Agentd now performs an
early capability check and rejects non-Unix startup before composing other
runtime owners. There is no emergency fallback to an unprotected path-based
Windows registry and no claim that this constitutes Windows production support.

The `secure-prompt-owner-platform` matrix runs source-bound checks on
Linux (real Unix Prompt Registry open and Agentd composition) and Windows
(explicit no-write/fail-closed denial). It does **not** skip or green-light the
repository's broader Windows Bazel/Agentd integration suites, which remain
blocked pending a separately reviewed Windows Owner with private ACL and
owner-token verification, reparse-point/hard-link rejection, handle-relative
safe opens, atomic replacement, directory durability and real crash recovery.
Keep all source/merge and cargo-deny gates unchanged.


### Encoder/generation binding on the paired OOD evidence (2026-10-11)

The optional Frozen/Learned model-side OOD receipts now bind the exact
`feature_manifest_digest` of the physically executed pinned Jina Stem,
together with `generation` and the per-Cell Head digest. The prequential
trial and its offline run manifest record the source generation, and the
independent three-way offline reviewer fails closed if a Head receipt belongs
to a different Stem manifest or generation, even when its Q24 Head bytes
happen to match. The diagnostic also reports those two frozen identities.

The production no-change arm retains its independent model revision,
weights digest and generation. These are *research-only, unsigned local
integrity checks*: neither a manifest SHA nor a generation number authenticates
the source process, attests the device, proves OOD utility or satisfies
signed independent NDU / production final-use.


### Byte-exact OOD model-sidecar integrity (2026-10-11)

When three matched OOD arms are provided, the reviewer now also requires
the trial's `offline_ood_model_receipts_sha256`. It extracts only the
Frozen/Learned model predictions (never the separately owned production
no-change records), reserializes them in the producer's actual event and arm
order, and verifies the byte-exact SHA of the original fsynced model
sidecar. Rewritten logits with unchanged Scope/Cell/revision/Head identities
cannot silently be presented as the original model trace. The
adversarial tests include unchanged-SHA tampering, replacing the SHA to
match forged logits, missing SHA and altered Encoder/Worker generations.

This is local **integrity**, not independent producer authentication:
an adversary controlling both the unsigned trial and its sidecar can
rewrite both. Real operator/observer signatures and future NDU outcomes
remain separately mandatory, and the reviewer can never promote a Cell.


### Bounded frozen Stem feature retention in the real learned-Head trial

`prequential_trial.py --max-feature-cache-bytes N` now limits retained
per-case Q24-decoded local frozen Encoder features, with a default of
64 MiB and an explicit registered envelope of 4 KiB through 512 MiB.
The cache is an exact Scope/Cell/case/ordered-input-identity LRU; miss and
eviction recompute the *real* frozen Encoder feature rather than returning a
synthetic cache hit. A single feature that cannot fit the byte ceiling
fails closed. The trial records the prescribed byte cap, observed resident
and peak retained tensor bytes, hits, misses, evictions and retained
feature count.

These bytes are the measured retained feature TENSOR STORAGE, not the
actual process RSS, peak PyTorch allocator usage, model memory, tokenizer
buffers, Windows filesystem handles or GPU VRAM. The independently
measured `max_observed_rss_bytes` remains a separate diagnostic and native
target-host 64/256/1024/4096 Cell p99/RSS/throughput/recovery qualification
remains pending. Resource-limited research trials must compare candidates
under the SAME precommitted feature cache ceiling. No production gate,
Final-use permission or learned Cell promotion is issued.


### Model-byte preflight before running any real Jina experiment

Use `hf download jinaai/jina-embeddings-v5-text-nano --revision FULL40SHA --cache-dir /approved/hf`
only in a separately approved staging step. Model execution does **not**
perform downloads. Review the exact remote Python files and each task Adapter.
Do not substitute `main`, a branch, a Git LFS pointer, a directory symlink or
a same-name replacement checkpoint.

For the staged, immutable local Hugging Face model cache:

```sh
python3 qualification/neuron-stem/snapshot_attestation.py \
  --model jina-v5-text-nano --revision FULL40CHARMODELCOMMITSHA \
  --task classification \
  --store-root /approved/hf/models--jinaai--jina-embeddings-v5-text-nano \
  --snapshot /approved/hf/models--jinaai--jina-embeddings-v5-text-nano/snapshots/FULL40CHARMODELCOMMITSHA \
  --out /evidence/proposed-local-snapshot-census.json
```

The first report is `observed_unapproved_shadow_only`, NOT an independently
trusted artifact. Have an independent reviewer inspect and freeze its full
file-by-file SHA256 manifest; do not automatically approve the hash calculated
by the same untrusted execution. Pass that separately frozen
`manifest_sha256` to any of the four real runner commands as
`--expected-snapshot-digest` (or per-model Text/Omni equivalents). This
recomputes every file hash both before and after model load and fails closed
on any mismatch.

For the real Jina trial process, explicitly set both
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before executing its CLI,
and enforce **OS-level outbound network denial** for reviewed custom model
code. The HF offline switches alone do not sandbox Python network access.
Offline fake-model tests intentionally remain independent of those switches.

The census requires actual `model.safetensors`, `tokenizer.json`,
`modules.json`, `config.json`, and the task-specific
`adapters/TASK/adapter_model.safetensors` and `adapter_config.json`. It
checks for external symlinks, Git LFS text pointers, duplicate/missing content
and size/count limits. It includes custom remote-code Python files in the
same digest, without pretending to sandbox their execution.

**Important boundary:** A checksum match is not a signature, independent
Final-use authorization, production Artifact CAS, attested physical model
load receipt, immutable mount guarantee, or evidence of learned utility.
Load-time hashing is separately accounted (`snapshot_attestation_ms`);
resource results retain the true research backend CPU/RSS and do not credit
those hashes as production Worker model load receipts. Offline conformance
tests only hash synthetic local fixtures; they never download Jina weights.
