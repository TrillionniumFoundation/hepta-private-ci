# Cell RSI: one configuration and separate acceptance stages

The initial source checkpoint is
`1e6bc8517d61fd42496bc0ed5082e34204b065dd`, tree
`fb2082b1ebc97843d827a064d1f3042c5f7a00ca`. Its recorded CI successes are evidence
for that checkpoint. Changed source requires its own execution and CI evidence.

## Joint configuration integrity

`scripts/hepta_cell_joint_config.py` checks one explicit source checkout and
eight content bindings: runtime, incumbent model, candidate model, trainer,
data, evaluator, budget, and adoption rules. A binding has exactly `path`,
`bytes`, and lowercase `sha256`; paths are relative to the supplied artifact
root. Directory artifacts must have a separately prepared immutable manifest
or archive. This checker does not recursively infer a model bundle.

The configuration uses schema `hepta.cell-joint-config.v1`, a `source` object
with `repository`, `commit`, and `tree`, an `artifacts` object with those eight
roles (spelled `incumbent_model`, `candidate_model`, and `adoption_rules`),
`required_workflows`, and `ci_evidence`. The last field is another file binding
to a complete GitHub `workflow_runs` response. An incomplete page, another
source/repository, absent workflow, or unsuccessful required run is rejected.
Every observed required run must have succeeded; failed historical observations
are not silently selected away. The source must be clean, including untracked
files, and its HEAD, tracked working bytes, and index must match the supplied
identity. Each tracked blob and executable mode is checked against the actual
Git tree, even when index flags or `core.filemode` hide a change from status.
Tracked symlinks bind their link text without following the target; submodules
are rejected. Ignored build products are not treated as tracked source, and a
clean source check alone does not prove what a build or process executed.

This tool explicitly requires POSIX descriptor-relative opens with `O_NOFOLLOW`
and `O_DIRECTORY`; it rejects unsupported platforms. The supplied artifact root
is opened once, each parent directory and regular file is opened relative to a
held descriptor without following symlinks, and all artifact identities are
reopened and checked before returning. The caller must own the supplied roots;
this is an observed integrity check, not a filesystem lock or immutable snapshot.

```sh
python3 scripts/hepta_cell_joint_config.py /evidence/joint-config.json \
  --source-root /checkout --artifact-root /evidence \
  --output /evidence/joint-config-integrity.json
```

The output is create-only and outside the checkout. It is an offline integrity
receipt. It does not authenticate the source of a supplied CI payload, establish
that a binary was built from the declared tree, inspect the training data's
meaning, or grant authority. Provider-origin readback, build provenance, current
owner capabilities, independent signatures, and actual execution remain separate
requirements. Missing inputs must stay missing; never fill an artifact role with
a synthetic stand-in to declare production acceptance.

## V2 state and complete consumption bindings

`hepta.cell-joint-config.v2` retains the source, artifact and CI integrity
checks above. V1 inputs still produce `hepta.cell-joint-config-integrity.v1`,
with an additional `legacy: true` marker; they have no complete consumption
bundle and cannot verify a V2 consumer readback.

V2 adds six independently hashed artifact roles to the original eight:
`state_schema`, `encoder`, `backend`, `incumbent_state_schema`,
`incumbent_encoder`, and `incumbent_backend`. The unprefixed roles describe the
candidate. Identical artifacts may share a file. These must be actual files
under the explicit artifact root, not unverified identity strings. Schema and
backend contents remain opaque: their hashes do not establish format support,
type correctness, numerical correctness, or model compatibility.

The extra top-level `compatibility` object has exactly `schema`, `models`, and
`state_transition`. Its schema is `hepta.cell-model-compatibility.v1`.
`models` has exactly `incumbent_model` and `candidate_model`, each containing
`model_sha256`, `state_schema_sha256`, `encoder_sha256`, and `backend_sha256`.
Every value must equal its corresponding verified artifact's SHA256. Unknown
declaration versions, missing roles, and mismatched contracts are rejected.

`state_transition` declares the proposed incumbent-to-candidate transition:

- `{"mode":"carry"}` conservatively requires identical model, state schema,
  encoder and backend identities. Even changed weights require reset or
  migration; identical declarations still do not prove semantic carry validity.
- `{"mode":"reset"}` declares a reset; it does not execute or prove one.
- `migrate` requires the additional `state_migration` artifact and exactly
  `mode`, `migration_sha256`, `from_contract_sha256`, `to_contract_sha256`.
  The endpoints hash the complete four-field incumbent and candidate model
  contracts. A migration's identity does not prove its implementation correct.

The V2 integrity receipt includes `bundle` and `bundle_sha256`. The bundle
contains schema `hepta.cell-consumption-bundle.v1`, source identity, every
artifact role's `sha256` and `bytes`, the complete compatibility declaration,
and the sorted required-workflow list. Its digest is SHA256 of compact JSON
with sorted keys, ASCII escaping, no nonfinite values, and no trailing newline
(`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False)`). Only fixed strings and integer sizes occur in this object.
Absolute roots and relative artifact paths are excluded; relocating identical
content does not create a new bundle. CI observations and timestamps remain in
the verification receipt and configuration hash, not the execution bundle.
Changing source, schema, trainer, evaluator, data, budget, or any other bound
content changes the bundle even if model bytes stay identical.

An optional consumer readback has exactly `schema`, `task_id`, `model_role`,
`bundle_sha256`, `model_sha256`, `state_schema_sha256`, `encoder_sha256`, and
`backend_sha256`. Its schema is `hepta.cell-consumption-readback.v1`;
`task_id` is 1–256 word characters or `./:@-`. The caller must explicitly supply
both the expected task identity and selected role, `candidate_model` or
`incumbent_model`; a readback from another task with the same bundle is rejected:

```sh
python3 scripts/hepta_cell_joint_config.py /evidence/joint-config-v2.json \
  --source-root /checkout --artifact-root /evidence \
  --consumer-readback /evidence/next-task-readback.json \
  --expected-model-role incumbent_model \
  --expected-task-id task-successor-1 \
  --output /evidence/next-task-binding-integrity.json
```

An evaluated NoUpdate uses `incumbent_model` and its incumbent schema, encoder
and backend; it cannot substitute candidate-side components even when the two
models share weights. The readback must match the complete bundle and selected
contract. This check authenticates neither the task identity nor the chosen
role. The trusted owner must supply them independently; a fabricated readback
cannot establish actual model execution or next-task consumption.
The consumer helper also rechecks the V2 verification status and bundle digest;
mutating a saved result's pins while retaining its old digest is rejected.

`compatibility_declaration_integrity` and `consumption_binding_integrity` report
only consistency of declared and observed bytes. The receipt explicitly keeps
`semantic_compatibility_verified`, `state_transition_executed`,
`model_execution_verified`, `actual_successor_consumption_verified`,
`consumer_readback_authenticity_verified`, and `authority_granted` false where
applicable. These engineering checks cannot authorize adoption, qualify a
scientific experiment, replace the original owner, or prove a migration ran.

## Learning and adoption criteria

The three initial learning profiles are retrieval/candidate ranking,
consequence/quality prediction, and action/stopping policy. Compare the same
functions as 1, 3, and 7 computational units with the same base model, data,
tools, context, and total budget. Keep evaluator and adopter independence in
every arm. Carry/reset state and alternative kernels are separate interventions.

The acceptance order is: joint configuration; actual selected-model next-task
use and recovery (including evaluated NoUpdate); causal learning gain with
retention and continued learning; a bounded physical structural transition;
paired old/new improvers on unseen targets; then domain/host/scale expansion.
Mechanism tests do not establish task gain, independent custody, physical
fencing, or successful structural migration. Prior inconclusive pilot results
and failed, cancelled, budget-stopped, or uncertain attempts remain in the
experiment denominator and cost record.
