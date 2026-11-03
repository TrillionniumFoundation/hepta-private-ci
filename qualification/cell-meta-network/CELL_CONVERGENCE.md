# Cell addressing, independent learning dependencies, and budget evidence

This candidate continues the native inventory implementation at
`ca77c10b25cf6eb1de91537c938a2beba597c886`. It retains the existing SQLite owner,
signed artifact publication and independent selection, shared encoder worker,
and native residual parameter reader. A cell remains a logical parameter/state
unit. These changes do not introduce one process, encoder copy, or database per
cell.

## Versioned addressing

`hepta.memory.inventory-semantic-router.v2` adds explicit query templates and
Unicode registered aliases to the existing semantic head artifact. Templates
declare supported read/arithmetic capabilities and capture complete entity and
workflow names. Every capture must resolve exactly to its corresponding
registry. A name such as `雪松港新区` cannot silently resolve to `雪松港`, and an
unknown workflow cannot disappear from a composition query. Conflicting routes,
multiple possible captures, unsupported phrasing, and extra instructions
abstain. ASCII case and whitespace are normalized for matching; there is no
transliteration or Unicode confusable folding.

The original text still reaches the pinned encoder. A learned head must agree
with the declared operation and pass its unchanged confidence/margin checks.
The grammar does not make a weak classifier accurate: valid Chinese queries
may still abstain. Version 1 artifacts retain their legacy address profile.

`prepare_semantic_v2.py` reuses an existing fitted head without changing weights,
thresholds, or training/calibration identities. It adds eight entity and eight
workflow aliases and fifteen declared bilingual phrasings. Its generated
120 known and 360 unknown cases measure declared grammar coverage, including
full-name suffixes and extra capabilities. They are not a fresh blind language
generalization benchmark. The existing Python scalar-f32 reference, native
live-worker evaluator, and actual-owner qualification consume this artifact.

## Independent parameter dependencies

The v2 native inventory bundle binds the complete current training-source set
of semantic and skill models separately. Each digest includes the scope, cell
kind, ordered address keys, and canonical source identities. New bundles carry
both dataset identities in their signed manifest. Publication still validates
both complete model lineages against a newly acquired owner snapshot.

Read-time checks select dependencies from the resolved route. A stable skill
update invalidates the skill model and composition, while an unchanged semantic
model remains readable; the converse also holds. Any changed or withdrawn source
used to train a model invalidates that entire model, even when the immediate
query addresses a different record. Exact events and holds remain authoritative
owner reads. Version 1 bundles preserve the combined training-cut contract.

After execution, the selected release and full acquired owner cut are still
revalidated. A concurrent source change, selection change, owner hold, lifecycle
fence, or request substitution cannot be converted into a partial successful
read. Import provenance can only map an immutable first revision; it cannot be
rebound to corrected owner values without actual retraining.

The existing `train_native_inventory.py` now accepts `--kind semantic|skill`
(default `semantic`). It cleanly rebuilds only the requested typed model from
current canonical records, exports the original numeric profile, and records
the per-cell dependency digest. The actual-owner test executes both kinds:
correction, stale relevant reads, continued unrelated reads, real training,
signed publication, independent selection, eight updated/retained predictions,
unchanged other-model artifact identity, and withdrawal.

This is independent training and parameter validity within one atomic selected
bundle. It is not two independent publication owners or two services. Reusing
the unchanged model bytes avoids unrelated retraining while retaining a coherent
release boundary and the existing final-use checks.

## Total-budget structure continuation

`BUDGET_PROTOCOL.json` fixes two seeds, four candidates, and a 12 CPU-second
allowance per candidate, including a share of common runtime setup. It reuses
`Structure`, `TensorCell`, and the three source-update phases from the earlier
study at `9a9a81cee17684fea111cec41237f77920ecac01`:

| Candidate | Changed capacity |
|---|---|
| Dynamic split | Two rank-4 adapters, training-gradient partition |
| Rank increase | One rank-8 adapter |
| Fixed experts | Two rank-4 adapters, fixed address routing |
| Pruning | Rank-8 parent expansion, task-value removal down to rank 2 |

All candidates have the same parameter upper bound. Pruning intentionally uses
fewer actual parameters; the report must not call these actual counts equal.
All run in one Python process on one CPU, with shared runtime imports and frozen
encoder features. Selection attempts, optimization, counterfactual diagnostics,
checkpoint writes, reload, evaluation, and coordinator work are charged. An arm
whose measured allocation exceeds the allowance is budget-invalid regardless of
quality. Failed attempts and their spent resources remain in the result.

Local credit is measured as the change in task utility when one adapter's
learning is counterfactually removed, keeping final routing and other adapters
fixed. Utility combines exact policy accuracy with exact status/value/full-trace
accuracy of the existing bounded interpreter over fixed programs and event
probes. This is a task-result measure, not loss reduction. Routing contributions
are measured separately; conditional contributions need not add up.

The published held-expression artifact is parsed only after all training ends,
but its reuse is exploratory. Two seeds and correlated wording groups do not
establish significance or open-world generalization. No split/prune candidate
is automatically activated. Historical parent training, encoder creation,
interpreter startup before the module clock, and final artifact transport are
identified separately; `full_cost_exact` remains false.

## Validation entry points

Ordinary native checks use `just test -p codex-hepta-agentd inventory_`.
The existing ignored qualifications require explicit deployment assets and a
new evidence directory:

- `inventory_semantic_actual_owner_path`, with the pinned encoder configuration,
  v2 head path/digest, and `HEPTA_NATIVE_INVENTORY_SEMANTIC_EVIDENCE_DIR`.
- `inventory_native_retraining_owner_cycle`, with the existing Torch interpreter
  and `HEPTA_NATIVE_INVENTORY_EVIDENCE_DIR`.

The Python study behavior tests use
`python -m unittest discover -s qualification/cell-meta-network -p test_budget_study.py`.
Run the fixed study with
`python -B qualification/cell-meta-network/budget_study.py --fixture <existing-formal-root> --output <new-directory>`.
Commands and test definitions are not execution receipts; attach the actual
results, failed attempts, environment identities, and process costs before
claiming that a qualification passed.
