# NumPy import failure: original evidence and narrow repair

Date: 2026-11-07. Scope: package import, test discovery, and unchanged public API.

## Finding

The architecture failure on PR #5306 is a real Python import failure, not a
scientific `HOLD`. Python unittest discovery imports package initializers even
when the selected test filename pattern excludes the package's own tests.
`ndu_semantic_state/__init__.py` eagerly imported `.state`, whose module imports
NumPy. The architecture and Rust detection jobs do not install NumPy.

This failure predates the replication/execution-gate changes. The original
initializer has the same Git blob, `17749f34c8a134c065e2a85d9b666b6888fd8280`, at
the #5198 source `006e744fbb10a6ee393166eed2e5d1e91f2fab1f` and the #5306 source
`c11208d7eec03f9329f811b3f44d7cca1fb9fa69`. Original #5198 source-job logs show
the same exception and 45 passing tests plus one package-import error.

## Original GitHub evidence retained

| Source | Run | Job | Observed result |
| --- | --- | --- | --- |
| #5198 source | 42318965227 | 128238554599 | 45 test successes + one NumPy import error |
| #5306 source | 42368651431 | 128391992004 | 45 test successes + one NumPy import error |
| #5306 base merge | 42368651431 | 128391992146 | 45 test successes + one NumPy import error |
| #5306 Rust change detection | 42368651489 | 128392531839 | 20 test successes + one NumPy import error |

`original-log-manifest.json` gives original job URLs, exact retained UTF-8 byte
counts, and SHA256 hashes. The four published `original-*.log.gz` files use
deterministic gzip (`mtime=0`); their decompressed bytes are the connector's
returned job-log content. The manifest binds both compressed and original bytes.
Original Actions runs were not rerun or overwritten.
Later native architecture checks were skipped after this import failure, so
these original runs do not establish that those checks pass.

## Repair

The initializer retains its original `__all__` and resolves those state API
exports on explicit access through module `__getattr__`. Resolved objects are
cached, with their original identities. Unknown attributes raise AttributeError
without importing state, including unittest's optional `load_tests` probe.
Explicit use of a state API still raises the real missing-NumPy error if NumPy
is unavailable. There is no fallback implementation, discovery bypass, custom
test loading hook, workflow change, or scientific-gate change.

Three added tests in the already-selected `test_state.py` run fresh isolated
Python subprocesses. They check discovery with a meta-path finder rejecting
NumPy, preservation of the missing-dependency error on explicit API access, and
preservation of named/star import identities when dependencies are installed.

## Local before/after verification

The replay used a fresh Python 3.12.14 venv created without pip or site packages;
an explicit import-spec check confirmed NumPy was absent. All three architecture
test modules, the Rust detection test, their two helpers, and their three read
workflow files were fetched at #5309 commit
`1c5436ae52771360cc9fd6eef6e365a1675cb502` and verified against Git blob IDs.
Their paths and IDs are recorded in `replay-ci-inputs.json`.

The replay contained these selected exact files and both NDU packages. Between
the complete before and after runs, only the package initializer was replaced.
This is a selected-source local replay of the exact original discovery arguments;
it is not a full GitHub Actions run or a full repository build. The outer GitHub
execution-record wrapper was not used for the replay. Its actual behavior is
among the 45 original tests, which run disposable Git repositories and subprocesses.

| Command | Before | After |
| --- | --- | --- |
| `python3 -m unittest discover -v -s scripts -p 'test_hepta_ci_exec*.py'` | 46 discovered: 45 pass, 1 NumPy import error | 45 pass, 0 errors, 0 skips (9.455 s) |
| `python3 -m unittest discover -s scripts -p 'test_hepta_rust_ci_feedback.py' -v` | 21 discovered: 20 pass, 1 NumPy import error | 20 pass, 0 errors, 0 skips (0.583 s) |

The disappearing item is unittest's synthetic `_FailedTest.ndu_semantic_state`
import-error placeholder; no actual test was removed. Use `before-exec-full.log`
and `after-exec-full.log` for the complete 45-test comparison. The earlier
`before-exec.log` was an incomplete replay before the third, deadline-specific
test module was fetched; it is retained in scratch but is not a full-run receipt.

The fixed source also passed the targeted dependency-installed command
`PYTHONPATH=scripts python3 -m unittest -v ndu_semantic_state.test_state ndu_portfolio.test_replication ndu_semantic_state.test_execution_gate`:
53 tests in 14.473 seconds, zero failures/errors/skips (18 state/import tests,
19 replication tests, 16 execution-gate tests). `git diff --check` passed.
This result was observed directly in the command output; the parent run retains
the separate integrated qualifier logs and receipt for publication.

## Source identity and limits

`import-fix-manifest.json` pins the two frozen changed files and the patch.
`ndu-import-fix.patch` contains only the initializer and state-test changes.

These checks establish the narrow import repair and regression behavior. They do
not establish remote Actions success, native owner authentication, independent
training authenticity, real five-family efficacy, power adequacy, adoption, or a
NoUpdate learning conclusion. Scientific admission remains `HOLD`; the native
owner/material/evaluator limitations in the existing review remain open.
