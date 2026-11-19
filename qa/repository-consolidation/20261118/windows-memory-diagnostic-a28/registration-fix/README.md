# Correct the Windows diagnostic's expression scope

## Hosted failure and correction

The published baseline workflow at `e2c3adbf1098b4a62e46a44376f0b4b0e836eb66`
failed GitHub's workflow validation before any runner was assigned. Run
`44353316661`, attempt 1, has zero jobs and zero native test executions. The
original public run page contains exactly this annotation:

> (Line: 26, Col: 21): Unrecognized named-value: 'runner'. Located at position 1 within expression: runner.temp

The complete 144,526-byte HTML is preserved without modification, SHA-256
`c7d1d585a632acf3e52289fdf6c573f07b0ea18b7693e66aa110f26a3ec67933`, alongside
the original run/jobs API records and the read-only retrieval receipts. The
previous archived validation remains intact. It checked YAML, Bash, Python,
receipt interpretation and exit propagation, but missed GitHub's context
availability rule. The registration failure is not a Memory-test failure.

GitHub's official [context availability table](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability)
permits `runner` in step environments, working directories and action inputs,
but not in a job-level environment. Its
[environment-file documentation](https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions#setting-an-environment-variable)
defines how a step writes a value to `GITHUB_ENV` for later steps.

The three-hunk patch changes only the workflow:

- Remove the invalid job-level `EVIDENCE_DIR` expression.
- Give the existing first PowerShell step a valid step-level value and write it
  to `GITHUB_ENV` before running the original Git long-path command. Propagate
  the Git exit code. Do not create the directory here: the unchanged source
  recording step retains its exclusive `exist_ok=False` creation.
- Give the always-running collector its own identical step-level value, and
  make artifact upload use the same absolute `runner.temp` path directly.
  Therefore evidence remains addressable even if the first step fails before
  environment propagation, checkout or Bazel setup.

The original target, complete exact-case argv, no-cache/no-retry settings,
Rust source, 250ms budget, assertions and collector Python are unchanged. The
other Bash/Python blocks are byte-identical to the original reviewed version.
No required workflow or branch ancestry is modified by this patch.

## Validation boundary

The context review enumerates all 14 expressions in the ten containing fields.
It detects the original unavailable `runner` reference as a negative control
and reports no unavailable context in the corrected workflow. The trigger,
permissions, pinned actions and all unchanged executable blocks are compared
directly. Two representative absolute Windows temporary paths, including a
path containing spaces, resolve identically for initialization, collection and
upload.

One new synthetic control executes the unchanged collector with the first-step
failure conditions: no checkout identity, no execution receipt, no Bazel output
root, and only the collector's valid evidence-path environment. It exits 1 and
preserves a deterministic FAIL receipt plus member manifest. It runs on Linux;
it is not a native Windows or PowerShell qualification.

The earlier 17 receipt controls and four pipeline controls are bound by exact
unchanged script bytes. They were not repeated. Bash syntax checking, the new
context/bootstrap control, and Codespell 2.4.3 completed before maintenance.
Prettier 3.5.3 and the real repository `just fmt --base e2c3adbf...` then exited
zero without changing a byte. The latter ran in a separate checkout of the
exact e2 commit and tree, using original formatter sources. No tests ran after
maintenance and no Windows Rust test has yet run in this diagnostic workflow.

Root independently reviewed the complete three-hunk patch and every expression
location. The original independently authored JSON is preserved as
`root-independent-review.json`; its SHA-256 is
`6019f5ef0552136f2a02d8162f1e2ea192925730c2848ca68dd9308d59c7f03e`.

## Frozen candidate

The corrected workflow is 14,348 bytes, SHA-256
`a403d2b9a92f2cdcf3b24e97474b5b08c76dc406dba4b30babf4db3cc96c16c7`.
The patch SHA-256 is
`75992e10ad7c96d73eb9b393b69e60928d62b154a9553df9fb5d52359137d6ed`.

Publication and the first real hosted Windows job remain the next required
observations. A registration success is not a native PASS. An isolated native
PASS would not, by itself, establish the cause or resolution of the original
concurrent Windows failure.
