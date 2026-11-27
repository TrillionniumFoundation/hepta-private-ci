# Bound shared-Stem model execution: source and measurement handoff

Baseline: `23f4ceae08e1cb47dde7ef44d1be7cc564f4a706` (PR #1698).
Code candidate: `b9c3a9b1393dd5bcd933086624719f0ee3e69f1a`.
Branch: `research/shared-stem-bound-model-execution-20261013`.
Scope: research/qualification only. No production installation, authority,
selected-artifact replacement or historical-result rewriting.

## What now executes

The old HF runner trains one Head. That result cannot be renamed a 16/32-Cell
V2 result. Its nine model/Head helpers are now shared through
`hf_encoder_kernel.py`; all twelve original function ASTs, including run/main,
were compared with the predecessor and remain unchanged. The new entry point
does not import the old runner's study/decision_421m dependencies.

`matrix_runtime.py` binds the V2 plan, execution contract, arm config, exact
workload bytes, local snapshot and first-party source files to one run. The
local HF adapter uses local-only safetensors, rejects partial/ignored loading,
compares every loaded tensor, freezes the Encoder and rechecks material/source
content before sealing. This adapter was implemented but NOT exercised with an
actual pretrained model in this session. Local integration uses an explicitly
marked synthetic Encoder and actual PyTorch trainable Head tensors.

Supported profiles: shared dense 16, shared sparse 16, directly initialized sparse
32, its explicit 64M capacity control, and the smaller shared Encoder control.
Split, NDU and replicated-Encoder profiles reject before loading instead of
silently executing a different algorithm. The profile is CPU FP32, one approved
scope and fixed 2..16 legal options. It is not the native Worker or GPU backend.

`matrix_bank.py` trains a bank of independently stored MLP Heads with a learned
input-conditioned gate. Dense/sparse controls use the same parameter shapes;
sparse routing actually evaluates selected sample subsets, not all experts and
a final mask. For a common feature dimension d, action width c and width_units q,
the main variants have exactly 32*(d+c+1)*q Head-plus-gate parameters. The explicit
64M capacity arm has twice that count, subject to actual per-Head/total ceilings.
This does NOT mean every allocation fills 32M/64M, nor that different Encoder
widths or configurations automatically match. Actual counts are exported and
checked by the existing paired audit. No dummy parameters balance the totals.

## Blind execution, sealed predictions, separate observation

`matrix_materials.py` admits a bound config and blind-workload JSON. Train rows
have labels observed no later than the data cutoff. Evaluation rows contain only
sample_id, source_group, scope, state, question, ordered options and input
availability time. Unknown fields (including answer/label/reward) are rejected.
Duplicate IDs, exact input or source-group overlap, mixed scopes, future labels
and changed evaluation denominators reject. This is not a proof against semantic
leakage, malicious timestamps, source mislabeling or cross-process access.

All Encoder calls receive a fresh public-input projection, not the training row
carrying a label. Evaluation invokes Encoder plus Cell bank afresh per request.
Training-input warmup is excluded only from request latencies and separately
recorded as work. Failed requests remain in the denominator. Feature allocation,
training steps, batch sizes and topology are bounded; full FLOP caps are NOT yet
enforced because the complete operation counter has not been connected.

The exclusive run directory retains bank.safetensors, execution.json and
predictions.json. COMMITTED.json is the last synchronized publication and binds
all three hashes. An externally retained seal ID is required by the observer
join. Partial/FAILED/linked/changed bundles cannot be consumed; a recomputed seal
cannot replace the retained reference. This is a local publication mechanism,
not native multi-writer CAS, independent signing, revocation or a threat-complete
file-system transaction. Process/OS isolation and independent retention remain
operator/owner responsibilities.

`matrix_export.py` joins separately supplied, content-pinned observer labels only
after prediction sealing. Observer, task/input identities and chronological
boundaries must agree. The result directly uses the existing paired-run schema,
so `paired_execution.py` can consume it without relabeling legacy results.
Availability-weighted accuracy includes failures as zero. Completed-only Brier
and ECE expose their denominator; a separate Brier variant charges the maximum
classification penalty (2) for each failed prediction. These are descriptive
metrics, not retention or statistical-superiority evidence.

## Execute from an actual source checkout

The target environment needs PyTorch, NumPy, safetensors and a reviewed compatible
Transformers installation plus approved local weights/data. No downloads or
package installations are performed implicitly by these entry points.
Use a checkout containing the source commit named in the execution contract:
`verify_source` compares each execution source to `git show <SHA>:<path>`.

Before running, use the existing `build_plan` / `freeze_contract`, then
`matrix_materials.freeze_config` to freeze numeric cost caps, data cutoff,
evaluation window, the supported arm, snapshot digest, upstream revision and
external material-approval reference. Keep one common workload/contract for a
paired comparison. Do not fill these fields with test fixture identities.
The following filenames are operator-supplied inputs, not generated evidence:

```sh
python qualification/stem-cell-v1/matrix_runtime.py \
  --plan plan.json --contract contract.json --config arm-config.json \
  --workload blind-workload.json --snapshot /approved/local/snapshot \
  --output new-run-directory
```

Retain the returned seal ID independently. Only then may the separate observer
produce the `hepta.stem.independent-labels.v1` receipt with the same seal/contract,
observer ID, exact task/input digests, labels and observation times. Never expose
that file to the model/training process. The export does not authenticate its
producer; a digest and matching observer name alone cannot establish independence.

```sh
python qualification/stem-cell-v1/matrix_export.py \
  --plan plan.json --contract contract.json --run-dir new-run-directory \
  --seal-id "$RETAINED_SEAL_ID" --observer independent-labels.json \
  --observer-sha256 "$RETAINED_OBSERVER_SHA256" --output new-export-directory

python qualification/stem-cell-v1/paired_execution.py \
  --plan plan.json --contract contract.json --contrast sparse_routing \
  --baseline dense-export/paired-run.json \
  --candidate sparse-export/paired-run.json --output new-pair-audit.json
```

Full inference/training/evaluation FLOPs, energy and peak memory remain null in
this executor. Search/migration are exactly zero because these five profiles
perform neither. Partial operation counts, current RSS, nominal parameters and
elapsed time are not substituted for missing physical metrics. Consequently the
pair audit remains blocked until genuine measurements are integrated before
sealing under an explicitly reviewed compatible profile. A synthetic test backend
also remains marked mechanism_fixture and cannot pass as pretrained execution.

## Verification and remaining acceptance

66 local tests passed, zero failures/errors/skips: the previous 38 plus 9 material,
11 runtime/tensor and 8 observer-export tests. Tests cover CLI imports, actual
bank training/routing/counts, repeatability, tensor-file comparison, publication
failure, sealed-byte tampering, independently retained seal references, future
label rejection and execute -> seal -> observe -> pair audit. The deliberately
incomplete synthetic pair is correctly blocked, not reported as an efficacy win.
Full raw output and source hashes are in BOUND_EXECUTION_TEST_LOG_20261013.txt and
BOUND_EXECUTION_TEST_RECEIPT_20261013.json. All ten changed/new Python blobs were
compared with the remote Git blobs. Python compileall, staged diff whitespace
checks and the twelve-function AST comparison passed.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
git diff --check
```

The session had CPU PyTorch but no Transformers, model snapshot, approved real
workload or attached project cloud host. The local source mirror is not a full
repository build. No actual pretrained 421M/smaller run, independent future-task
gain, full repository/Rust/Actions result, prospective merge acceptance, native
1024/4096-Cell run, energy measurement or multimodal generation was completed.

P1 still requires target-host model execution, complete measured-cost integration,
separately retained observer provenance and joint/cached/conditional representation
comparisons. This change implements only the joint representation. P2/P3 still
require the actual split/consolidation and NDU/System2 owner paths to be wired into
this executor with their costs and compatible state transitions. P4/P5 trained
multimodal generation, native scale/recovery and longitudinal evidence remain open.
These gaps are not waived by a passing source-level test suite.
