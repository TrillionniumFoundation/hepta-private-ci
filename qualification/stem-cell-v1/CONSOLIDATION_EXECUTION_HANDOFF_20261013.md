# Behavioral consolidation into a smaller Cell bank

Parent: `2e3b16df48918ecfcbac756447ed9fe66e3db6a6` (PR #1733).
Tested Python candidate: `5babf2b0a85ef3c5c3ad4468d78c176871b8dee1`.
Branch: `research/shared-stem-consolidation-20261013`.
Research candidates only. No main merge, selected-model mutation, native topology
installation, production deployment or rewriting of historical evidence.

## Actual compression, not another replay-only stage

The existing matrix_growth/runtime path now optionally calls
`consolidation_training.consolidate` after family specialization and its retention
gate. It constructs a real 16-Head CellBank from the trained 32-Head FamilyCellBank
with exactly half the Head-plus-gate parameters at the same per-Head width. The
student starts from sibling zero and the parent-group gate, then learns from
supervised old/new fitting labels and temperature-scaled KL(teacher || student).
Divergent weights are never averaged. This initialization is not a function-
preserving merge, and its successful training is not guaranteed.

Only fitting rows enter optimization. Detached teacher logits are cached, without
copying a second teacher model. Teacher parameters remain unchanged; extra teacher
forward calls, new student construction, actual optimization and validation work
enter the existing live meter. Old/new fitting examples, steps, optimizer tensor
bytes and reference payloads have explicit denominators. The original reference
cache remains because the original retention baseline is still needed.

Both the initial caller parent and the 32-Cell teacher may still be live during
student training. The common lifecycle cap therefore covers parent + teacher +
student where applicable, not just the final student. Both logit-reference caches
and the reserved fitting subset enter the retained-feature payload preflight.
Gradients, optimizer states, activations, shared Encoder weights and transient
allocator overhead are not mislabeled as that payload or model-parameter cap.

The final student continues to execute two Heads per request. Half the bank
parameters is not half the full Encoder/model storage, full process memory,
latency, FLOPs or energy. Extra compression training has a real amortization cost.

## Two fixed internal gates, no progressive baseline reset

After the final student update, every old/new validation source group must satisfy
teacher-relative accuracy-drop and NLL-increase limits. The original retention
session then rechecks the student against the ORIGINAL pre-specialization baseline.
The original reference-parameter and logit digests must match across both stages.
Passing relative to the latest teacher alone cannot accumulate successive losses
against an ever-changing baseline. No overall mean can hide a regressing subgroup.

These are internal point-estimate selection gates on the existing pre-cutoff
validation folds, not independent future retention or statistical confidence bounds.
Validation labels do not enter gradients; the same finite validation panels are
used for sequential acceptance, so repeated-selection effects remain an external
experimental-design responsibility. There is one declared candidate, no automatic
threshold relaxation, retry or fallback mislabeled as successful compression.
Rejected attempts and all their costs must remain in the outer study denominator.

A rejection raises ConsolidationRejected with actual subgroup observations and
training counts. run_bound writes FAILED and expected final task IDs; no success
seal is returned. A successful internal candidate still exports
retention_established=False and production_authorized=False.

## Bound identities and preserved compatibility

Supply a `consolidation_policy` to the existing freeze_config to choose config V6.
It requires retained parent-group specialization and the existing meter/lifecycle
contract. Omission preserves older V1-V5 behavior and protocol hashes.

The policy schema is `hepta.cell-consolidation-policy.v1` with fields:
steps, temperature, distillation_weight, max_accuracy_drop and max_nll_increase.
Freeze these before running; the permissive synthetic fixture values are not
scientifically validated task thresholds. The same policy must bind comparable
consolidated controls. No new experiment arm, wrapper runner or CI gate is added.

Execution V3 and paired export V3 explicitly distinguish original 32-Cell training
history from output_profile `consolidated_parent16_mlp.v1`. The final safetensors
and predictions belong to the 16-Cell student. Compression record validation checks
teacher/student geometry, exact half-parameter counts, all live model parameters,
original retention references, subgroup counts and true training denominators.
Existing growth/retention validation is factored without changing its AST and
runs on a separately validated precursor projection. That projection never
replaces the actual student inventory exported to the paired audit.

Compressed and uncompressed outputs cannot pass as the same output stage or
training protocol. Content digests and structured records still do not authenticate
observers, prove semantic information isolation or qualify native state recovery.
The checkpoint roundtrip test rebuilds the explicitly bound 16-Cell geometry;
loading a same-shaped checkpoint into an unrelated topology is not supported.

## Verification actually observed

The unchanged predecessor passed 185 tests. The final focused suite passed twice:
204 distinct tests, zero failures/errors/skips (185 retained + 9 consolidation
training tests + 10 export/integration tests). Tests perform real CPU PyTorch
optimization, safetensors roundtrip, teacher immutability and alias checks,
validation-label exclusion, real subgroup degradation refusal, live-cap preflight,
strict metering, sealed observer export and output-stage mismatch rejection.
All nine remote Python blob hashes match the exact local tested bytes. Compileall,
staged diff whitespace and the old population-validator AST comparison passed.
The existing arithmetic registry and CI thresholds were not relaxed.

The first full integration run failed because its test incorrectly expected the
direct-initialized fixture to compress successfully. Actual training instead
violated its original-baseline new-validation gate. The test was corrected to
expect that genuine rejection, not by weakening the gate or changing the actual
candidate outcome. Raw failure logs are retained. A separate validator-only
normalized comparator test is explicitly synthetic and is never exported as a
completed direct experiment; its pair still blocks on missing physical evidence.

The independent diagnostic uses a synthetic 4D Encoder and real tiny bank training.
The split teacher has 896 parameters and its accepted internal student 448, with
1,792 simultaneously live model parameters (448 initial + 896 teacher + 448 student).
The directly initialized teacher also has 896 and a 448-parameter candidate, with
peak 1,344, but that candidate is REJECTED by the original retention gate.
There is no completed successful paired efficacy or equal-quality efficiency
experiment. These diagnostic labels are not pretrained 421M execution.

Raw baseline, core, failed-development, both passing logs, diagnostic source/JSON
and HF-import failure are in the downloadable package; hashes are retained in
CONSOLIDATION_TEST_RECEIPT_20261013.json. This environment also emits an unrelated
artifact_tool spreadsheet-warmup warning on some Python process startups; it is
retained in the raw logs, not counted as a unit-test failure or silently removed.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

The separate installed-HF attempt failed at import with missing Transformers:
zero of its three tests executed, and none is counted among the 204 passes.
Direct repository DNS failed. No approved pretrained model/data run, project-cloud,
GPU/native/1024-4096-Cell, full-repository, Rust or hosted-CI result was obtained.
This is a CPU source slice; just and the full codex-rs checkout are absent.

## Remaining acceptance

Actual approved weights and independent old/new final panels, observer authenticity
and evaluation costs, whole-operation energy/memory/work measurement and rejected-
attempt denominators remain necessary. One offline compressing candidate is not
multi-generation lifelong consolidation, selective pruning, NDU/System2, native
ownership/recovery, multimodal generation or 10T/100T equivalence. Final bank size
reduction does not by itself close any of those scientific or production gates.
