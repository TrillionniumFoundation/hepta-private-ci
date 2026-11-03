# Windows process environment on the dependency union

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO** until this exact source
passes its original Windows suites. This does not close the full repository CI
or authorize product admission.

The parent is dependency union `0b9da54535a7795b2433947a479e6d9e71525e0a`.
The only build or product change is eight explicit `common:windows --test_env`
entries from #4727: `ProgramFiles`, `ProgramFiles(x86)`, `USERPROFILE`, `APPDATA`,
`LOCALAPPDATA`, `ProgramData`, `SystemDrive`, and `PATHEXT`. They provide the
standard Windows paths to native child processes under Bazel's strict action
environment. No full environment forwarding, production process-tree change,
queue change, timeout increase, thread restriction, filter change, or PowerShell
prewarm is introduced. All original target sources, manifests, locks, lifecycle
assertions, and existing skip-filter policy remain the parent's exact bytes.

## Prior evidence and its limits

The original no-prewarm run `41692381139` at upstream source
`112c05026a36a3555b01886c5bad9bb9f9c1d2e8` and test merge
`5333650cac868e4a1d2c9efbd9d80ab656a8c655` completed both original targets.
Each ran the complete outer Git suite with 33 passes and queue suite with 35
passes, no outer failed, ignored, or filtered cases. Its existing Git stdin test
also runs one selected child case with 32 filtered cases; that child is not
added to the outer denominator. The four wrapper XML files each represent one
Bazel target, not one XML case per native test.

Both original artifact sizes and SHA-256 digests, ZIP CRCs, raw logs/XML, and
the two actual `Executed 2 out of 2 tests` job logs were checked. The 11 recorded
inputs match their exact Git blobs after the original Windows checkout's exact
LF-to-CRLF conversion. The original harness confirmed they stayed unchanged.
The current qualification sets checkout line endings to LF and binds all tracked
Rust source and the listed build inputs before and after execution.

That upstream tree also contains separate Git command-quoting fixtures and
queue terminalization changes absent from this dependency-union parent. Those
changes are deliberately outside this eight-variable port. The old green run
therefore supplies provenance, not proof that the current narrow port passes.
The retained original reports exercise acceptance controls only; they are
never presented as a new native execution.

## Current original qualification

Both immutable source-head and pull-request test-merge jobs use the original
MSVC Windows runner and wrapper, original two target labels, original 120-minute
job budget, `--nocache_test_results`, and ordinary test concurrency. No
PowerShell process is launched before those original targets for a readiness
probe. Fresh native logs and XML must agree; both original outer inventories
and required lifecycle cases must pass, with no ignored or filtered outer tests.
Original failures, both target reports, actual command, source snapshots, and
compact Bazel execution logs are retained. Bound source changes, including any
lock mutation, reject qualification.

Reproduce on the prepared native Windows runner:

```sh
python -m unittest discover -s qualification/windows-process-env-current -p 'test_*.py' -v
python qualification/windows-process-env-current/run_qualification.py --output /fresh/evidence
```

`HEPTA_EXPECTED_COMMIT` must equal the immutable checkout. The original Bazel CI
setup supplies its normal output roots, MSVC tools, and cache configuration.
`HEPTA_BASH` is the absolute executable of the workflow's running Git Bash,
resolved with `cygpath -w "$BASH"`; the wrapper records its bytes and version.
The failed first current run selected the Windows WSL launcher through a bare
`bash` lookup and executed zero tests. That negative evidence is retained in
`hosted-fb1c`; it does not establish a failure or pass of either native suite.
