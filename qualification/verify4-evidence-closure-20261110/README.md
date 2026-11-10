# VERIFY-4 engineering qualification

This candidate extends the common VERIFY head
`a2cd828aad47c56ac8c01dc2e423454eca7eafae`. It first imports the three missing
treatment files verbatim from `1609a21e5113440bab9de75ccd2afc233e29eec0`, then
adds model-content binding, retained label attestations, design-aware matched
admission, complete treatment denominators and a separate repair-lineage journal.
See [VERIFY4.md](../../experiments/verification_cell_verify1/VERIFY4.md) for the
authority boundaries, compatibility changes and remaining field requirements.

## Measured local result

| Measurement | Result | Scope |
| --- | ---: | --- |
| Unit/regression tests | 226 passed; 0 skipped | One final joint discovery run |
| SQLite confirmation rows | 72 / 72 | Controlled fixture confirmation set |
| All SQLite rows | 96 | 12 training + 12 calibration + 72 confirmation |
| SQLite effect subprocess calls | 270 | Workload effects, separate from dispatch smoke |
| Dispatch scenarios | 9 | Controlled replay/recovery fixtures |
| Actual dispatch subprocesses | 17 | Actual calls recorded by dispatch smoke |
| Newly admitted independent real tasks | 0 | No admissible field bundle was located |
| Full physical cost measured | No | Unknown costs remain explicit |
| Scientific admission / production authority | HOLD / NONE | No field-effectiveness or adoption claim |

[RESULT.json](RESULT.json) contains command boundaries, UTC timestamps,
durations, exit codes and original log hashes. Local execution used Python
3.12.14 and NumPy 2.3.5. The measured results do not add scoped test counts to the
final joint total, and do not count imported treatment code as a new field trial.

## Evidence and provenance

| Artifact | Contents |
| --- | --- |
| [ENGINEERING.zip](ENGINEERING.zip) | Exact executed source, complete final logs, raw SQLite/JSONL/dispatch artifacts, earlier failing counterexamples and resolved review evidence |
| [SOURCE.json](SOURCE.json) | Executed and published source byte/AST hashes, published Git blob identities and original upstream tree |
| [FORMAT.json](FORMAT.json) | Formatter/lint commands, hashes, exit codes and the explicit source-identity boundary |
| [REVIEW.md](REVIEW.md) | Resolved integrity, inference, authentication and SQLite commit-order defects |
| [PORTABILITY.md](PORTABILITY.md) / [PORTABILITY.json](PORTABILITY.json) / [PORTABILITY.zip](PORTABILITY.zip) | The actual first Windows failure, explicit test-connection closure repair, retained-handle diagnostics and follow-up source/format records |
| [MATCHED_REGRESSIONS.json](MATCHED_REGRESSIONS.json) | Before/after unsupported-design, mixed-allocation and zero-net-benefit counterexamples |
| [RISK_REGRESSIONS.json](RISK_REGRESSIONS.json) | Before/after stale risk identity and missing-label denominator counterexamples |
| [HOST_OBSERVATION.json](HOST_OBSERVATION.json) | Bounded host inventory, incomplete search coverage and unresolved operation status |
| [UPSTREAM_CI.json](UPSTREAM_CI.json) | Observed common-candidate CI runs and job states; these are not results for this new head |
| [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) | Size and SHA-256 of every top-level qualification deliverable except the index itself |

The ZIP has a separate `ARCHIVE_INDEX.json` for every archived member except its
own index. Its 581,229 bytes exceed the repository's 512,000-byte default asset
budget, so the existing allowlist mechanism registers only its exact SHA-256:
`812ec80778a256f47ff17d05e62967a2d1d32c3668701535677373f316f83358`.
The size checker, threshold and existing entries are unchanged; replacement
bytes are not covered by that pin.

Historical failures remain historical failures; the final joint run
is under `final_run/`. `executed-reproduce.py` is the exact runner that generated
that run. The published runner adds explicit confirmation-row aggregation and
formatting; it does not retroactively replace the executed runner.

The complete repository was not materialized locally. Publication builds Git
trees on the original complete remote tree, preserving unrelated repository
contents. Whole-repository build or CI success is not implied by package tests.

## Formatting and exact-head CI

The final local execution used the pre-format bytes in the ZIP's
`tested_source/`; they stayed unchanged throughout all three commands.
Repository-required `just fmt` then completed. Because its registered scope
does not include these experimental Python paths, pinned Ruff 0.15.13 explicitly
formatted and checked all 16 changed Python files; lint and diff checks passed.

Fourteen changed Python files retained identical raw ASTs. The other two changed
only function-docstring indentation; executable ASTs and cleaned docstrings are
identical. Local tests were not rerun after formatting, as required by AGENTS.md.
`scheduler_identity()` includes raw source bytes, so local dispatch identities
must not be attributed to the formatted published head.

The first native Windows run subsequently found six test-cleanup errors caused
by test SQLite handles not being explicitly closed. [PORTABILITY.md](PORTABILITY.md)
retains that failure and the narrow fixture repair. The paragraph above describes
the initial formatting stage; the two test files have a separately recorded
functional resource-lifetime follow-up in `SOURCE.json` and `PORTABILITY.json`.
The original local result and archive are preserved without rewriting history.

The existing `hepta-verify1.yml` workflow explicitly checks out and asserts the
PR head SHA on Linux, macOS and Windows before running package tests, SQLite
confirmation and dispatch smoke. Consult the PR's exact-head Actions run and its
uploaded artifacts for published-source results. Neither the previous common
candidate's successful directed run nor this local pre-format run substitutes
for that CI. At evidence freeze, no new-head CI result is claimed here.

## Reproduce

From the published repository root, in an environment with NumPy installed:

```sh
python -B qualification/verify4-evidence-closure-20261110/reproduce.py --output /tmp/verify4-new-run
```

Use a new output directory; the runner refuses an existing result directory.
The output records the source actually executed. For the historical local
source, extract `ENGINEERING.zip` to a separate directory, then copy the extracted
`executed-reproduce.py` to
`tested_source/qualification/verify4-evidence-closure-20261110/reproduce.py`
(creating the two directories). Invoke that copy with a new output path; its
repository root is derived from its file location, not the shell's working
directory. Reproduction creates new observations and timestamps; it
does not rewrite the archived original run.

## Admission remains external

Mandatory native permission, signature, ownership and constraint checks remain
separate from learned check scheduling. Authentication callbacks require the
host's current external trust policy; fixture keys are not independent custody.
Matched inference requires the supported authenticated assignment design,
complete labels and verified costs, strictly positive terminal-error reduction
and net benefit, and frozen practical/statistical thresholds. Even a passing
engineering record remains externally reviewable only.

Real-task confirmation still needs an independently controlled frozen task and
source-group roster, original allocation evidence, independently adjudicated
terminal labels, original check/repair/readback receipts and full-cost coverage.
The host search was incomplete, so failure to locate that bundle is not evidence
that it does not exist. No independent real tasks are invented or admitted here.
