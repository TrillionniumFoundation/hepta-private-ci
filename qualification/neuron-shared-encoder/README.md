# Hepta Neuron Shared Encoder Qualification V2

**Shadow-only experiment runner; cannot authorize production.** A local CPU smoke passing does not establish Laya accuracy, shared-Encoder reuse equivalence, future NDU gains, worker throughput, journal durability, or a production release.

This project continues the earlier 24-head/36-load experiment. It adds exact input identities, grouped/time-disjoint evaluation, real model adapters, separate original Laya decision-head baseline, batched gated-Cell tensor execution and a fail-closed gate. It is an isolated qualification harness, **not** a new production `hepta-neuron` runtime owner or an actual Hepta worker/ledger integration.

## Dependencies

Python 3.10+ (verified locally with 3.13), PyTorch and pytest. `laya` with its compatible `transformers` stack is additionally required for genuine Laya trials; `transformers` is needed for the standalone ModernBERT checkpoint. Never install or download a model implicitly in a test run. Benchmark results depend on driver, dtype, actual hardware, input length and batch policy.

## Local reproducible smoke

Run from this directory:

```bash
python -m pytest -q tests/test_qualification.py
python -m neuron_shared_encoder.experiment synth-data --allow-synthetic --output smoke_dataset.jsonl --data-count 32
python -m neuron_shared_encoder.experiment validate --dataset smoke_dataset.jsonl --output validated.json
python -m neuron_shared_encoder.experiment head --allow-synthetic --dataset smoke_dataset.jsonl --output head_results.json --steps 16
python -m neuron_shared_encoder.experiment stress --allow-synthetic --output stress_results.json --rounds 2
python -m neuron_shared_encoder.experiment gate --output gate.json
```

`head`: Linear, FiLM, Rank-8/16, MLP, SwiGLU × 2K/16K/64K/262K *upper parameter budgets*. Actual trainable counts and actual optimizer-state bytes are reported; 2K Linear vs 262K MLP are **not equal parameter count**. Shared Encoder forward is frozen and excluded from per-Cell trainable parameters, but must be measured as an amortized system cost in a full run. Train, validation, OOD and future windows are disjoint at `(principal,source_group)` level; future begins after the train and validation timestamps. The OOD AUROC is `1-max_softmax` (a detection diagnostic). An untrained Head is not the persisted Hepta no-change baseline.

`stress`: exercises actual CPU PyTorch batched projections and Cell-conditioned gates at 64/256/1024/4096 cells, 10/50/100% active and same/partial/distinct inputs. The frozen projection is synthetic and does not represent 395M Laya. Batch p95/p99 are **batch service times**, not per-request SLOs. Python feature materialization costs are included, but worker scheduling, GPU memory, CAS checkpoints, WAL, crash recovery and final-use authorization are **not** included. Cache rechecks are currently caller-supplied `admitted=True`, which is not a real verification capability. The prototype cache MUST NOT be transplanted into production unchanged.

## Real pretrained offline trial (when provisioned)

Provide a local already-downloaded **pinned** checkpoint including `model.safetensors`, tokenizer and model configuration; record the SHA-256 of the exact model weights, the **complete checkpoint bundle** and the dataset bytes. Stage the bundle in a private, read-only directory with real files, not Hugging Face cache symlinks. This qualification hashes every file and refuses symlinks or missing local encoder config; it checks the same bundle before loading and after inference. Operator-computed hashes alone do **not** constitute an independent signature or trusted source attestation; review and pin the manifest separately. The real loader fails closed if weights are missing or modified. Running with a synthetic encoder is explicitly prohibited for `representation`:

```bash
MODEL=/absolute/path/to/pinned/laya
DATA=/absolute/path/to/approved-labelled-splits.jsonl
SHA_MODEL=$(sha256sum "$MODEL/model.safetensors" | cut -d' ' -f1)
SHA_BUNDLE=$(python -c 'import sys; from neuron_shared_encoder.bundle import checkpoint_bundle_sha256; print(checkpoint_bundle_sha256(sys.argv[1], "laya-joint"))' "$MODEL")
SHA_DATA=$(sha256sum "$DATA" | cut -d' ' -f1)
python -m neuron_shared_encoder.experiment representation \
  --encoder laya-joint --checkpoint-dir "$MODEL" \
  --weights-sha256 "$SHA_MODEL" --checkpoint-bundle-sha256 "$SHA_BUNDLE" \
  --dataset "$DATA" --dataset-sha256 "$SHA_DATA" --output laya_real_shadow.json
```

`laya-joint` builds question+option marker sequences via Laya's own encoding functions and measures the original Laya model's true `system_one` policy (when that pinned package/checkpoint is locally installed). The lightweight head receives **lossy pooled CLS + option-marker statistics**, intentionally quantifying the representation loss; this does not claim Laya functional equivalence. Checkpoints using parallel option attention are explicitly rejected pending a compatible masked Encoder path. The exact installed Laya package source identity also needs independent attestation.

For a distinct ModernBERT-base checkpoint, use `--encoder modernbert-joint` and a local Transformers-compatible checkpoint and tokenizer. It uses an explicit, **different** joint-string format, so it is not a bit-level Laya tokenizer/control. Compare predictions on the same frozen records/splits and normalized prediction semantics. Higher-level Organ Expert Bank parameter totals are reported separately from per-Cell parameters.

## Expected real dataset JSONL

Each line must include these fields:

```json
{"row_id":"r1", "source_group":"episode:123", "event_time":"2026-09-01T00:00:00+00:00", "split":"train", "principal":"p1", "organ_id":"o1", "cell_id":"c1", "state":"approved text", "question":"route?", "options":["A","B","C"], "label":1}
```

A complete file must have `train`, `validation`, `future`, `ood`, with a stable number/order of choices (2..16). Labels are integer option positions; no source group may appear in two splits and the future times must follow all train and validation timestamps. Only one scoped Cell is admitted per head trial, avoiding accidental cross-principal training. Sensitive data-use policy and consent are **not** established by JSONL validation and must be granted by the existing Memory/Replay owner outside this harness.

## Promotion gate and native integration blockers

Even if an evidence JSON contains every named field, `gate` remains **BLOCKED**: it does not verify issuer identity, independent signatures, revoke status, NDU benefit, final-use tokens, artifact CAS, state migrations or CNS route cutover. An independent Hepta Evaluator, Selector and Executor must evaluate and approve a signed candidate. A real no-change baseline must be frozen for each Cell; testing untrained heads is insufficient.

Native integration still required after successful real model experiments:

1. `hepta-infer-worker-host` driver must physically separate shared Encoder ownership, organ adapters and Cell heads and execute real batched requests. This Python project does **not** patch those Rust owners.
2. Replace the prototype feature cache's caller-supplied bool with exact final-use and live source entitlement checks. Bind Encoder, tokenizer, preprocessing, input/option layout, principal/purpose, generation, authority epoch and revocation; invalidate on reload or revoke.
3. Measure inference **per request and per batch** on target hosts, independent Head optimizer footprint, GPU peak, p95/p99, checkpoint/WAL amplification, stale-read denial and restart recovery.
4. Train and evaluate full Laya, pooled Laya Head, ModernBERT-base, Organ Expert Bank on the same approved, grouped future-window protocol. Add independent NDU and negative-transfer evidence; only then propose promotion.

_No change in this harness alters any Hepta production contracts, grants or model versions._

## E1–E5 strict research qualification (V3, no deployment)

The independently versioned shadow module is `neuron_shared_encoder.validation_v3`.
It does not replace the immutable Rust inference owner, sign model receipts, apply
NDU decisions, change CNS routes or enable model final-use. The existing native
`GatedHeadCpuDriverV2` is a fixed Q24 elementwise multiplier; V3 introduces
`static_gate` and a genuinely input-dependent `dynamic_gate` **in PyTorch
research only**, not in the Rust production worker.

### E1 — same-task, same-budget real Encoder matrix

Require one SHA-256-pinned dataset/split manifest and persisted no-change
baseline, a common train seed, steps, optimizer, batch and learning rate, plus
pinned weight/bundle/tokenizer SHA-256 for all four candidates:
`laya-joint`, `mmbert-joint` (140M candidate), `granite-joint` (97M),
`modernbert-joint` (149M candidate). The E1 contract scanner accepts a
**complete schema** as `SCHEMA_COMPLETE_UNVERIFIED`, never `PASSED`.
Separate offline `representation` runs and operator-verified artifact/dataset
receipts are still required for any scientific comparison; genuine Laya
`system_one` requires its original model/checkpoint and cannot be replaced
by pooled CLS logits. Generic Hugging Face mean pooling for
mmBERT/Granite/ModernBERT is an explicitly separate control; it does not
assert equivalence to an official model-specific pooling or teacher policy.
No implicit download, remote-code trust, fake checkpoint or synthetic
Encoder is allowed for E1 real claims.

To run all four **genuine** offline E1 model candidates after every pinned
checkpoint is available, supply a JSON matrix with each Encoder's
`local_path`, `weights_sha256`, `tokenizer_sha256`, `bundle_sha256`,
and the common dataset/split/no-change/training pins. Then use:

```bash
PLAN_SHA="$(sha256sum e1_matrix.json | cut -d' ' -f1)"
DATA_SHA="$(sha256sum approved.jsonl | cut -d' ' -f1)"
python -m neuron_shared_encoder.validation_v3 e1-run --input-json e1_matrix.json --input-sha256 "$PLAN_SHA" --dataset approved.jsonl --dataset-sha256 "$DATA_SHA" --output e1_real_shadow.json --dimension 128
```

The runner preflights all four local paths and tokenizer bytes, verifies
the bundled/weight hashes via the existing offline adapter and never substitutes
a synthetic checkpoint. A missing model blocks the entire matrix. It trains
the same Head candidates on each frozen Encoder output, with train-only
normalization, and separately records the original full Laya policy.
The model bundle pin and local results are not independent operator signatures
or proof that an external no-change baseline was genuinely frozen.

### E2 — capacity and fixed-Gate folding

`e2-heads` trains Linear, static Gate, input-conditional sigmoid/SiLU Gate,
FiLM, rank-8/16, MLP and SwiGLU using the same frozen features, source splits,
optimizer and update budget. Budgets 2K, 16K, 64K, 262K are *upper bounds*;
actual parameters and optimizer bytes are recorded. After training, the
static Gate is folded to a Linear weight matrix and its maximum absolute
logit difference is recorded. This proves mathematical redundancy to
floating-point tolerance, not bitwise Q24 equivalence. Q24 rounding and
hardware parity require independent native tests.

### E3 — full-joint input versus public-input / Cell-state fusion

`e3-reuse` collects both `encoder_forward_invocations` and
`encoder_forward_rows` from actual calls to the adapter; counts are not
inferred from the logical Cell count. The public-input key excludes Cell
state but includes principal, purpose, generation, authority epoch,
Encoder/tokenizer/normalizer digests and evaluation split. It cannot
bypass a real source-entitlement or signed final-use check. The Cell-local branch now uses the **same frozen, SHA-pinned Encoder**
with a fixed state-only prompt and options; it does not inject a synthetic
hash when the Encoder is real. The decomposed execution explicitly counts
**public + private-state** physical Encoder rows and reports the signed
difference against joint rows, including cases where decomposition costs MORE.
Public features are reused only within principal/organ/epoch/revision/split;
state features are also fenced by Cell identity. This is a genuine
frozen-state control with a trained fusion Head, **not** a separately trained
State Adapter nor a production feature cache. The synthetic smoke route
remains visibly synthetic. Real pooled-input quality, future independent
evidence and signed owner/final-use checks remain unqualified.

### E4 — frozen no-change versus candidate; never promotion

`e4-future` requires a *real, externally prepared* frozen no-change
probability snapshot and a distinct candidate snapshot, each with an
operator-supplied exact file SHA-256. They must contain the ordered
`row_ids`, probabilities for all dataset rows, `dataset_sha256`,
`cell_scope` [principal, organ_id, cell_id], `source_commit`,
`artifact_digest` and `role` (`frozen_no_change` or `candidate`).
It fails closed on scope/dataset/row/order mismatch, invalid probabilities
or identical artifacts. It reports grouped future-window bootstrap 95%
intervals for Brier improvement, 15-bin ECE, NLL, OOD detection AUROC and
future source-group negative-transfer fraction. The optional positive
*shadow signal* requires at least 30 future groups, positive lower CI and
zero materially degraded groups; it is **not** an NDU decision. The
independent Evaluator must still verify causal improvement and receipt
authenticity; Selector and Executor remain separate owners.

### E5 — complete host telemetry schema, no fabricated measurements

`e5-host` requires one record for each of 64 / 256 / 1,024 / 4,096
Cells, with exact host/run/commit, encoder physical call/row/input
counts, requests, throughput, CPU, peak RSS, GPU peak if applicable,
per-request and per-batch p95/p99, WAL bytes, crash recovery, lost-replay
counts, CAS/signature/CNS latency. A complete operator-submitted JSON
is `COMPLETE_UNVERIFIED` until independent signed source, target-host
measurements, generation-fence tests and operator authorization are proven.
Synthetic `stress` does not fill in missing worker/host fields.

### Example isolated smoke

```bash
cd qualification/neuron-shared-encoder
python -m pytest -q tests/
python -m neuron_shared_encoder.experiment synth-data --allow-synthetic --output smoke_dataset.jsonl --data-count 32
DATA_SHA="$(sha256sum smoke_dataset.jsonl | cut -d' ' -f1)"
python -m neuron_shared_encoder.validation_v3 e2-heads --allow-synthetic --dataset smoke_dataset.jsonl --dataset-sha256 "$DATA_SHA" --output e2.json --steps 2 --budgets 2048 16384
python -m neuron_shared_encoder.validation_v3 e3-reuse --allow-synthetic --dataset smoke_dataset.jsonl --dataset-sha256 "$DATA_SHA" --output e3.json --steps 2 --budgets 2048 16384
```

Read the generated JSON `evidence_class`, `production_admission`, and
unverified fields before interpreting any values. CI intentionally exercises
missing real Encoder and target-host receipts and requires both to remain
blocked. The E4 frozen baseline is **not generated from random/untrained
Heads**, and all V3 claims are research/shadow only.


### A5 — exact five-arm Stem selection (non-authorizing)

The requested five-model grid is available separately from the original
four-model E1/Granite control. `e1-five-plan` requires the exact
`mmbert-small`, `modernbert-base`, `gte-modernbert-base`,
`mmbert-base` and `laya-421m` arms. Each entry binds `repository`,
40-hex upstream `revision`, local SHA-256 weight/bundle/tokenizer digests,
`backend_kind`, license approval, and a common frozen dataset/split/baseline
and AdamW training protocol. Laya additionally requires local package review.
A matrix with any omitted, extra or swapped model fails closed.

Use `e1-five-plan` on a hash-pinned manifest first; once all **real offline**
weights and an approved dataset exist, run `e1-five-run` with that same
manifest, `--dataset-sha256` and `--dimension 128` or other registered
1–512 width. The runner preflights all five paths before loading, verifies
the tokenizer and bundle hashes, and checks the published mmBERT/ModernBERT
hidden width. It records actual forward timings, original Laya System One
and separate trained Heads. In particular, the GTE arm here uses a
**generic masked-mean Transformer control, not the official model-specific
GTE Embedding API**; do not report it as an official GTE leaderboard score.
Official GTE pooling/task adapters need a separately pinned run.

The complete five-arm schema is `SCHEMA_COMPLETE_UNVERIFIED`, not proof that
all five models ran. All outputs remain shadow-only; no real weights or
qualified approved data are supplied by this PR.


### B — three-way prequential Head evidence (no independent signatures)

`python -m neuron_shared_encoder.abc_evidence b-threeway --dataset
/approved/frozen.jsonl --dataset-sha256 SHA --input-json
/approved/threeway.json --input-sha256 SHA --output /evidence/b.json`
requires the same exact row identities for externally obtained
`frozen_no_change`, `frozen_head`, and `learned_head` snapshots.
The candidate snapshot supplies a per-row pre-update Head digest;
a label-free, ordered event journal seals all three probability vectors,
the input, initial matched frozen Head and observed prediction time before
the label-availability timestamp. Distinct future_1/future_2 windows cannot
overlap in clock or source group. Report grouped bootstrap improvements
against BOTH controls, Brier/ECE/NLL, old-task retention, OOD false
acceptance and abstention at the precommitted threshold.

A self-authored hash/timestamp does not establish authentic pre-label
publication. A validated offline B report remains `NOT_AUTHORIZED`
until independently signed NDU, external baseline/evaluator and full
production FinalUse gates exist.

### C — text -> vision -> audio -> video cost truth (shadow)

`python -m neuron_shared_encoder.abc_evidence c-stages --input-json
/approved/paired-stages.json --input-sha256 SHA --output /evidence/c.json`
requires each stage to preserve the pinned text probe, all prior modality
tasks with identical cohorts, and actual FULL-active Cell coverage at
64, 256, 1024, and 4096. The same host, source commit and paired
text-control workload must be present. Counters include physical encoder
forward rows AND batches, CPU/RSS/GPU, request p95/p99, WAL, CAS/signature/CNS
p99 and unclean crash recovery. Multimedia frames may legitimately create
MORE encoder rows than requests, so that ratio is not silently rejected.
It reports incremental parameter/weight/RSS cost and prior-task score
changes; negative changes are retained.

This C checker accepts self-reported metrics only as
`SCHEMA_COMPLETE_UNVERIFIED`: it cannot authenticate host, worker,
real model, signature, timing, external truth or recovery. The test suite
uses deliberately synthetic contract fixtures, not real measurements.


### Explicit A/B/C joint gate and retention constraints

After collecting individually pinned A5, B and C reports, pass
`{"A": {...}, "B": {...}, "C": {...}}` to the `abc-joint` command.
The gate requires all five **real local model** A5 arms, learned Head
improvement against both frozen controls across the B future windows,
complete C stage telemetry, and the same dataset identity in all reports.
Even an entirely complete operator-authored bundle remains
`RESEARCH_REVIEW_CANDIDATE_UNVERIFIED`, never a production selection.
Neither file-presence nor an asserted signature field is accepted as NDU
or effect authorization.

B requires the learned Head to start from exactly the immutable frozen
Head weights; the first future prediction must use that same initialization.
C requires an explicit `max_retained_task_score_drop` preregistered
before evaluating later modality stages. Any old-task score loss over the
limit blocks the research precheck instead of being hidden by new-task gain.


### A5 safety: no silent non-Laya truncation

The real `OfflineEncoder.encode` generic mmBERT/ModernBERT/Granite path
first tokenizes the complete joint question+options+state input with
`truncation=False`; it rejects even one example whose complete token
count exceeds `--max-length` before dispatching the Encoder model.
Padding happens only after this check. The previous
`truncation=True` behavior could compare **different tasks** across
different checkpoints and is no longer accepted. This is a strict
experiment-equality gate, not a production tokenizer.

Laya's own `Agent._encode_state` is still a private upstream encoder
that may already have truncated the input before its post-encode
length can be inspected. The public Hepta harness can reject its
over-length returned IDs but **cannot independently attest zero
pretruncation** for Laya. Do not use Laya from this path as a strictly
zero-truncation-qualified A5 winner without separately instrumenting
the pinned upstream Laya tokenizer and proving lossless option and
state encoding.


### B: post-label Head successor continuity

The original `prelabel_journal.records` remains **strictly label-free**.
A *separate* `postlabel_updates` journal now supplies one committed
successor per chronological future event, with exact digest of the
pre-label record, observed label identity, update disposition, label
availability time, post-label update time, and predecessor/successor
Head digests. The next prediction must consume the last Head successor
and cannot precede the previous update. `no_update` must preserve the
exact Head digest; `updated` must have new weights. The final Head
digest must match the last successor. Missing updates, forks and
post-label-injected prediction fields are rejected. These
**self-reported** observations still require an independent, durable
source to establish true pre-label ordering and cannot grant authority.

B window scores now report both `brier` (multiclass sum) and
`brier_normalized` (divided by option count); grouped paired deltas
always use the latter. Do not rank reports using incompatible Brier
units.


### B: matched first-prediction and immutable feature/runtime identity

Frozen and Learned controls now must pin identical
`encoder_bundle_sha256`, `feature_pipeline_sha256`,
`runtime_profile_sha256` and `input_contract_sha256`. The very
first future event must have the same probability distribution for
the learned Head as its untouched same-initialization Frozen Head
(up to 1e-7 float tolerance), or no learning claim is made. Digest
agreement by itself is insufficient: this catches alternate pooling,
input layouts, or output heads masquerading as online plasticity.
Subsequent Head changes require the separately chained post-label
journal. The independent production no-change arm is NOT forced to
share these artifacts.


### C: same Stem, measurable active modality and recovery

All four modality stages bind the exact same
`shared_text_stem_sha256`, while each added sensory tower has its own
`modality_adapter_sha256` and paired, source-approved
`paired_media_dataset_sha256`. A shared text-probe digest by itself
was not sufficient: a different underlying text model could be passed
off as a new sensory differentiation.

Every full-active 64/256/1024/4096 Cell row now requires an observed
`run_id`, `active_modality_peak_bytes`,
`head_resident_bytes`, `queue_peak_depth`, `wal_fsync_count`,
and `recovery_trace_sha256`. A non-text stage without measured active
modality memory, a full-active cohort without Head memory, a
non-durable WAL, or a missing crash trace is blocked. Intermediate
stage deltas retain both total RSS and active-modality peak
differences. These are **operator-supplied, unverified** measurements
until independent target-host/owner receipts establish their origin.
The separate counterfactual truth-flip executor in PR #1774 remains a
distinct required evidence producer; C's scalar task scores alone
cannot demonstrate that the model actually used images/audio/video.


### E3 fourth arm: *learned* lightweight state, not an extra Transformer

E3 retains **three different cost paths**: (i) frozen joint
state+question+options Encoder, (ii) public-question Encoder + frozen
state-only Encoder and ordinary Head (which may consume MORE forwards
than joint), and (iii) public-question Encoder + real trainable
Cell-local byte n-gram State Adapter + light Gated/Linear Head.
Path (iii), `quality_shadow.public_plus_trainable_lightweight_state_adapter`,
uses train-only gradients for the State Adapter and Head. All parameters
are counted together under the same 2K/16K/... total Cell ceiling,
including an AdamW optimizer memory report. Private state processing
uses deterministic, explicitly lossy byte 1–3-gram counts, without
another full Transformer call. It also reports actual raw bytes
processed and elapsed featurization time; this cost is **not zero**.
Fixed public projections and input normalizers are fitted or frozen
without using future labels; no production feature sharing is claimed.

This fourth arm lets research compare *true cheap state adaptation*
against full-joint accuracy and frozen double-Encoder input decomposition.
It is an experimentally trainable control, not evidence that byte hashing
preserves all decision signals. If image/audio/video, binary state, huge
states or privacy permissions are not supported by this local text
featurizer, E3 must use a separately qualified state adapter.


### E3 trainer falsification: train-only gradient proof

`state_fusion.py` now emits canonical FP32-value SHA-256 diagnostics for
the complete trained Cell, state adapter and Gated Head, without requiring
NumPy. Adversarial trials keep all training examples unchanged while
flipping validation/future/OOD labels and assert exact equality of ALL
trained weight digests. Flipping train labels must change the digest.
This demonstrates label partitioning for the *research* optimizer
rather than merely reporting matching parameter counts; it does NOT
authenticate data collection, permissions, independent pre-label
production, or causal NDU outcomes.


### B pre-label seal correction: observation time is not future truth

The immutable `prelabel_journal` no longer accepts the future
`label_available_at` timestamp. Actual label availability is a
separate **post-label observation** and is compared with the already
sealed prediction timestamp. The post-label update must occur strictly
after the observed label availability. This avoids manufacturing
knowledge of when a not-yet-observed outcome arrives in a purported
pre-label artifact. All timestamps are still self-reported here;
an independent append-only producer and signed witness are required
before a real selection.


### E2/E3 fixed option-space proof (future-label leakage regression)

The number of Head output classes is now resolved only from a **frozen,
registered choice count** (`len(options)`) for all real dataset/CLI
experiments, and never from a future/validation/OOD label maximum. The
standalone Python APIs accept an explicit `num_classes`; if absent they
derive the class count from the training slice ONLY and fail closed when
future labels fall outside that frozen geometry. A future-only class can
be tested if it was already part of the publicly registered choices:
its Head output neuron exists before learning, even if that class was
not observed in training. This removes a subtle previously present
future-label information channel in E2/E3 Head construction.


### A/B/C evidence integrity: literal JSONL and option meaning

The frozen dataset reader now rejects **duplicate object keys at every
JSON nesting depth**, NaN/Infinity extensions, blank physical JSONL rows,
symlinked source paths and a file whose content changes between byte hash
and the end of parsed-record validation. Raw SHA-256 alone does not
resolve ambiguous parser interpretations. This is a research integrity
check, not cryptographic authorization.

The E1/E2/E3/A5 class-index Head contract additionally requires one
fixed **ordered** set of 2–16 legal options across all records. Merely
enforcing the same number of options is insufficient: a swapped option
changes the meaning of logits, making the paired Head accuracy a
misleading comparison. For tasks with per-example variable options,
evaluate the original option-conditioned Laya decision directly or
implement a separately qualified per-option scorer; do not assign
variable semantic labels to fixed output neurons.


### C semantic necessity: real media counterfactual results, not embeddings alone

The A/B/C combined research review now requires the **separate,
source-bound paired-media counterfactual scorer output from PR #1774**,
plus an externally precommitted `media_policy` tied to the frozen C
`protocol_sha256`. The `media-pairs` command audits its
`hepta.stem.paired-modality-audit.v1` output and requires held-out
image substitution, held-out audio substitution, and actual video
*temporal reordering* with original and changed truths. Structural
counts, distinct source groups, both-correct fraction and failure to
respond to media changes must satisfy the policy's stated limits.
A video retrieval score or changed embedding cosine alone does not pass.

Example evaluation envelope:
`{"report": <PR1774 output>, "policy": {"schema":
"hepta.stem.media-review-policy.v1", "protocol_sha256": <matching-C-protocol>,
"minimum_pairs_per_group": <frozen-int>, "minimum_distinct_source_groups_per_group":
<frozen-int>, "minimum_both_correct_fraction": <frozen-float>,
"maximum_unresponsive_fraction": <frozen-float>}}`.
This is a schema example, not an authorization or recommended numeric
threshold. The research verifier does **not** authenticate the observer,
whether those thresholds were truly preregistered, or source media
bytes. Even an entirely passing result remains
`SCHEMA_COMPLETE_UNVERIFIED` and `production_admission=BLOCKED`.

Missing media evidence now blocks the combined A/B/C *research review
candidate*, even if all model/Head and four-scale resource fields are
present. A separate authenticated Evaluator/Selector/Executor remains
necessary for a production decision.


### JSON number overflow is not a valid observation

All three offline JSON entry points (dataset JSONL, E1/E5 manifest and
B/C/A+B+C evidence) now reject not only literal `NaN`/`Infinity`
and duplicate keys but also valid-looking numeric exponents such as
`1e9999`, which Python would otherwise quietly decode as infinity.
No allegedly pinned model input or measured resource may become an
infinite Python float. This is research input validation, not a signed
source-attestation mechanism.


### C cross-source integrity: actual paired predictions must belong to C's final model

The multimodal audit now retains the registered final **video-stage**
composite model, media source and preprocessing SHA-256 identities.
The `abc-joint` envelope must additionally include the full
`media_predictions` input used by the PR #1774 paired-media scorer
alongside its `media_counterfactual` summary and frozen policy.
The raw input is canonicalized with PR #1774's JSON encoding and hashed
to exactly match `prediction_sha256` from that scorer. Its
`model_sha256`, `preprocessor_sha256` and `source_sha256`
must also match the final C-stage identities; scored cohort counts
must match the associated source-bound raw modality pairs.

This prevents a researcher from attaching a genuine image/audio/video
truth-flip score from a *different* model, data source or processor
to this A/B/C resource/learning comparison. It remains an **untrusted
offline** cross-source consistency check, not a replay of PR #1774's
entire scorer, independent media truth verification, or signed owner
attestation. The real C final stage and paired scorer must actually
use the same complete multimodal model/pipeline; otherwise the honest
result is BLOCKED, not a guessed projection/identity mapping.
