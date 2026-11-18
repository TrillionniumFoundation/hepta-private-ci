# Mechanical repair of the online_v4 formatting gate

The build-test job for evidence head
`74bf3fdea6ff77d253212e623ce3a619c35c2983` failed the Python formatting gate.
This change applies the repository's locked Ruff formatter to exactly the
24 `online_v4` files named by that job. Their Python ASTs, including every
string and other constant value, are unchanged. No model, semantic verifier,
or test suite was executed for this mechanical change.

## Original failure

[Job 134860547887](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44319657521/job/134860547887)
ran `just fmt-check` and reported:

```text
uv run --frozen --project scripts ruff format --check scripts .github
24 files would be reformatted, 488 files already formatted
```

`CI_FORMAT_FAILURE.zip` retains the complete original 240,803-byte job log
as its sole `CI_FORMAT_FAILURE.log` member,
SHA-256 `6ca7080a6e209b117c7abea975e36fbd1292360540ccf1c48836fdacfb13f2af`.
`CI_FORMAT_READOUT.json` retains all 24 file names, the bounded one-time log
retrieval receipt, and the comparison showing their original bytes were the
same in executed candidate `4d9fc82` and evidence head `74bf3fd`.
The failure is retained; it is not relabeled as a successful CI run.

## Mechanical verification

Before formatting, `BEFORE.json` recorded each file's byte hash, full AST hash,
and constant-value hash. `BEFORE_BYTES_AND_AST.zip` retains all 24 original
source files and their full AST dumps. The dumps use
`ast.parse(type_comments=True)` and
`ast.dump(annotate_fields=True, include_attributes=False)`; source positions
are omitted, while code structure, type comments, and string values remain.

The formatter command uses the unchanged `scripts/uv.lock`, which pins Ruff
0.15.13. Only the 24 named paths were passed to the mutating formatter.
`AFTER_RUFF.json` proves 24/24 AST and constant-value equality and limits the
tracked source diff to those paths.

All 512 tracked Python files under `scripts` and `.github` were materialized
before checking the full gate, including files absent from the initial
sparse checkout. The exact CI command then exited 0 and reported
`512 files already formatted`; its intent, stdout, stderr and actual exit
receipt are retained as `RUFF_CHECK_*`.

As required by `AGENTS.md`, `just fmt` was subsequently run from `codex-rs`
and exited 0. `AFTER_JUST_FMT.json` confirms the same 24/24 AST and constant
equality, with no further source byte changes. `JUST_FMT_*` retains that
command and outcome. This scoped local success is not a claim that every
repository CI job passed.

## Frozen execution boundary

The original model directories, manifests, source packages, FREEZE records,
run receipts and published raw archives are unchanged. The historical model
executions remain bound to `581c4c0` and `4d9fc82`; this newly formatted source
head has zero model executions and gains no learning, adoption, or scientific
qualification from the formatting result.

Formatting changes source bytes, so a future execution using this source
must bind its own actual source inventory. This change does not rewrite an
old inventory or relax any source or model gate. The independent Fence
startup failure and cargo-deny failure remain separate CI observations.
