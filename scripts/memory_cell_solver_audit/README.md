# Independent receipt audit for the actual repair study

This read-only auditor checks the uploaded evidence against the exact committed
source inventory. Its implementation was prepared before the first hosted model
result was available. It never imports a model runtime, runs a decoder, executes
a repair candidate or modifies source/evidence files.

The caller supplies the extracted evidence root and an independently verified
expected document containing the Git head/tree, source-file identities, original
task contracts and model manifest. The current expected document is derived from
35 local files whose Git blob identities were checked against the committed
GitHub tree. The evidence does not get to choose those expected values.

```sh
python3 -B scripts/memory_cell_solver_audit/audit.py \
  --evidence /absolute/extracted-artifact-root \
  --expected /absolute/independently-bound-expected.json \
  --output /absolute/new-audit-result.json
```

Checks cover the frozen protocol, source/runtime qualification, source-only
model inputs, exact proposed edits, original 76/21 test IDs, missing-tool refusal,
observed prompt/output tokens, all attempted and unexecuted denominators, and
final formatting/worktree receipts. The output separates consistency of evidence
from actual task success. Missing or contradictory evidence cannot pass.

Seven local checks used retained real successful and failed semantic receipts,
plus an incomplete-evidence refusal. They ran no new task subprocess or model.
This remains a trusted-runner consistency audit, without hardware attestation,
hostile-candidate containment, independent future cases or a strong-RAG claim.
