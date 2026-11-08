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
