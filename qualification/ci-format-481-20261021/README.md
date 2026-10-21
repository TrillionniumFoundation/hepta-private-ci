# Original CI Python formatter closure

Original PR #2968 job `119194391214` in run `39583123088` failed its formatting
step on source `48177153ad04605338c3a9a8dbd17defee9981bc`, checked out as the
prospective merge `3c32bedb07239b0cbdb38d100836258165cae633` against base
`57636c7a17d4847eb5fd712409816fd040b4e90f`. The complete original decoded job log
is preserved as lossless XZ with its byte count and digest.

The failure was exactly one Python file:
`.github/scripts/test_v8_cargo_smoke.py`. The other 182 Python files already
matched the repository's frozen Ruff formatter. The current combined source's
file was compared byte for byte with the original 481 file before repair.

The original failing command was reproduced locally:

```text
uv run --frozen --project scripts ruff format --check scripts .github
```

It exited 1 with the same one-file finding. The two existing V8 smoke regression
tests then passed before formatting; their loops cover eight native and Windows
workflow/variant combinations. The repository's own Ruff formatter normalized
the quoting of two Python string literals in the fake Cargo executable fixture.
Parsed ASTs before and after the change are identical when source locations are
excluded. The emitted shell text, assertions, matrix and actual workflows do not
change.

The same full Python formatting command then exited 0 and reported all 183 files
already formatted. The required final `just fmt` invocation has a separate
receipt. No tests were run after formatting. This is a narrow source correction;
the failed original CI job remains failed, and its continued Rust jobs were not
cancelled or replaced.

Command JSON receipts and log archives record every original failure and
successful execution. `source-before.json` and `format-change.json` bind the
actual source bytes. The runner is the already archived
`../combined-durability-20261021/runner.py.raw`. The later published head still
requires its own unchanged CI gates.
