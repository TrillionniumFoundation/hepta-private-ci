# Independent receipt audit for the actual repair study

This read-only auditor checks the uploaded evidence against the exact committed
source inventory. Its implementation was prepared before the first hosted model
result was available. It never imports a model runtime, runs a decoder, executes
a repair candidate or modifies source/evidence files.

The caller supplies the extracted evidence root and an independently verified
expected document containing the Git head/tree, source-file identities, original
task contracts and model manifest. The historical v1 expected document was derived from
35 local files whose Git blob identities were checked against the committed
GitHub tree. The evidence does not get to choose those expected values. Version 2
also requires the independently verified fields described below.

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

## Version 2 source and receipt binding

The expected document still contains the independent head, tree, files,
contracts, contract_hashes and model. It additionally requires:

- recipe_source_utf8: the complete original recipe source text, including its
  whitespace. The auditor first checks its UTF-8 byte count and SHA256 against
  files["scripts/memory_cell_solver/recipe.json"]. Only then may its parsed
  fields define generation, runtime, trajectory and retrieval limits. Every
  recipe field must equal the frozen protocol; evidence cannot raise its own
  call or token budgets.
- source_root: the independently identified absolute POSIX checkout path
  used by the frozen qualification. It is only a logical receipt identity.
  The auditor never opens that old host path or runs code from it.
- format_argv: the independently frozen formatter argument list. For the
  existing workflow this remains ["just", "fmt", "--base",
  "1823dc1dc82b3c4ad7d980d80863bbc763c36941"].

Qualification and command documents must match their original protocol byte
identities. Counts, runtime profiles, tool pins, registered harness and unique
arguments are checked as in production admission. This does not recreate an old
runtime or authenticate execution hardware.

The original preparer records sys.executable while its runtime profile records
the resolved executable path. If those logical paths differ, the independent
expected document may register exactly one qualification_python object with
the fields argv0 and resolved. argv0 must equal the frozen command's first
argument; resolved must equal the frozen runtime profile's Python path. Both
must be normalized absolute POSIX paths. Without this independent mapping,
literal equality is still required. An alias declared only in the evidence does
not authorize itself. The auditor preserves the profile and command byte pins;
it never resolves old host paths or claims to prove that a historical symlink
existed. Existing expected documents using the same literal path need no new
field, while an unregistered differing alias is refused.

Each successful gate must retain exactly the candidate bytes produced by the
model-edit path. Its source and workspace inventories are derived independently
from the fixed contract, source pins and that candidate, then compared to the
retained workspace bytes and observed records. Ruff also retains an expected
inventory record. Codec originally retained only observed inventories; the
auditor derives the expectation without manufacturing a missing old file.
Failed attempts remain failures and may retain partial gate evidence; they are
not promoted to successful bound gates.

Final formatting requires a real final-format-result.json with the closed shape:

    {
      "schema": "hepta.memory-cell.final-format.v1",
      "argv": ["just", "fmt", "--base", "1823dc1dc82b3c4ad7d980d80863bbc763c36941"],
      "command_returncode": 0,
      "log_returncode": 0,
      "log": {"bytes": 0, "sha256": "the actual retained final-format.log digest"}
    }

The producer records the actual formatter and log-pipeline return codes and the
same retained log bytes. Zero is required for both; the example's log values are
placeholders, not an execution receipt. Empty source patches or status files
alone cannot establish formatter success.

An old expected document or archive lacking these fields fails closed with
HOLD_INCOMPLETE_OR_INCONSISTENT. Do not backfill a success receipt or rewrite
historical source, evidence, result or failure files. A new consistency audit is
not a recertification of a previous model run.

## Pure consistency controls

    python3 -B -m unittest discover -s scripts/memory_cell_solver_audit -p 'test_*.py' -v

These five methods use only small synthetic metadata and source-text files.
They preserve the original recipe thresholds and 76/21 test-ID lists as data;
they never execute those task tests, candidate programs, a model, a downloader,
a formatter or a training routine. The original 18 solver test methods and their
assertions are unchanged. CI registration is maintained in the caller workflow;
a local pass does not itself establish an automatic gate.
