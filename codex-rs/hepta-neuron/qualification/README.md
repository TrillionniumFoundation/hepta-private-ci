# DecisionCell backend qualification

This package-local qualification harness compares frozen pretrained encoders with
real, separately trained organ/cell adapters and typed heads. It is not a second
Neuron owner, inference runtime, artifact selector, or computer-effect executor.
The authoritative product path remains the guarded V2 owner described in
[the V2 development guide](../../../docs/modules/neuron.runtime/V2_DEVELOPMENT.md).

## Scope and evidence

The generated panel is deliberately synthetic. It contains separate training,
tuning, calibration, test, retrospective-time-labelled, and OOD partitions.
Synthetic time labels are not prospective calendar windows. High accuracy on this
panel establishes neither GUI competence nor production calibration or efficacy.
The base remains frozen; training updates the actual organ/cell adapters and heads,
not the pretrained backbone. Candidate target scoring uses a shared pointer scorer,
not a classifier over fixed target positions. Each artifact binds its tensor groups.

The program retains failed/unsupported cases and emits content-addressed datasets,
embedding tensors, trained weights, manifests, calibration, per-model receipts and
comparison summaries outside Git. A summary is a recommendation for a bounded
experiment only. It cannot issue selection, independent acceptance, activation,
promotion, release, or rights to redistribute a model.

## Source identity before model execution

`model_snapshot` must verify every locally consumed file against the exact upstream
Git commit before executing the backend. A matching revision string is insufficient.
Ordinary files match Git blob hashes; LFS files match their upstream SHA-256 and
size. Extra, modified, duplicate, escaping and malformed files fail closed.
`normalized_hub_manifest` and `verify_snapshot_files` implement this check without
trusting a mutable local directory name as model provenance.

Offline execution remains possible for diagnostics, but it does not fabricate an
upstream observation. Such a receipt cannot pass exact-revision admission. Auditing
cached files later produces a separate record; it does not rewrite or requalify an
older execution. A modified tokenizer/preprocessor requires a separately bound
derivation, never silent editing under the original upstream model revision.

Source identity, safe-code review and licensing are different checks. Matching LFM
custom-code hashes is not code review; a permissive license tag is not an independent
license decision. Unreviewed remote-code candidates cannot become internal-shadow
recommendations merely by producing a good score. No candidate in this synthetic
panel is eligible for runtime selection.

## Immutable Laya loader inputs

The pinned Laya source calls `_fix_tokenizer_config` inside `Agent.__init__` and
rewrites a list-valued `extra_special_tokens` field in place. Feeding the original
upstream directory to that constructor therefore changes the bytes previously
admitted by the snapshot verifier and prevents later exact-revision replay.

`laya_loader_view.py` now copies the admitted snapshot to private regular files,
checks the copy against the previously admitted inventory digest, and performs
only `laya-tokenizer-compatibility-v1` there. Its receipt binds both the original
snapshot and effective loader-input digests, the exact before/after tokenizer
bytes, changed paths and this adapter's code digest. The original snapshot is
never repaired or relabelled in place. A previously changed cache must be retained
as diagnostic evidence and replaced by a separately materialized exact upstream
snapshot before another qualified run.

The caller verifies the view after loading and again after model use; artifact
replay requires the identical effective loader identity. Undeclared writes, source
drift, symlinks, invalid configuration and silent device fallback reject. The
private view is removed on close. This is an integrity/compatibility adapter, not
an OS sandbox, code-review approval or evidence that a model is selected. The
trusted-parent-filesystem assumption still applies during loader use.

```sh
python3 -m unittest -v test_laya_loader_view
python3 -m unittest -v test_tensor_bundle
python3 artifact_replay.py --receipt /qualified/output/receipts/MODEL-DIGEST.json \
  --model-root /qualified/models --device cpu --output /qualified/replay.json
```

## Commands

From this directory, use an isolated environment with the pinned direct dependencies
in `requirements-bakeoff.lock.txt`. That file is not a transitive, hash-locked build.
Keep the concrete environment and runtime identity with each executed experiment.
Do not install or upgrade dependencies from a live Cell invocation.

```sh
python3 -m unittest discover -s . -p test_snapshot_identity.py -v
python3 -m unittest discover -s . -p test_decision_cell_bakeoff.py -v
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  --model-root /qualified/models --device cpu prepare
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  --model-root /qualified/models --device cpu run --model mdeberta-v3-base
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  summarize --models mdeberta-v3-base
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  verify --models mdeberta-v3-base
```

`snapshot_identity.py` can audit a pinned local model against public HTTPS metadata
without importing PyTorch, sending credentials or executing model code. It writes
a new audit with the validator digest and upstream response digest. Its records
are local qualification evidence, not registered cross-module authority contracts.

Run each backend in a separate process. The comparison refuses mixed dataset,
script, source commit/tree, maximum input length, or duplicated model identities.
A real equal-condition bakeoff must additionally freeze device, concurrency,
precision, tokenizer/preprocessor and the complete end-to-end workload. Report
encoder extraction separately from full decision and actuator latency.

## Remaining product qualification

The selected inference owner must consume the exact admitted base/organ/cell/head
bundle and calibration/OOD artifacts. This training harness does not install that
owner, migrate live state, or sign its own artifacts. Browser/native effects still
require the registered semantic contract, final-use authority, durable operation
identity, target generation and trusted terminal observation.

External teacher traces need an independently admitted input/data-use scope and
applicable output-training rights before training a distributable artifact. Teacher
agreement is not ground truth. Retain independent environment outcomes, human review,
student-state coverage and prospective holdout; do not replace them with synthetic
labels or a successful HTTP response.
