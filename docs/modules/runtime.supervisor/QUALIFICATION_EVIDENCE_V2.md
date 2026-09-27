# Supervisor qualification evidence v2

## Scope and provenance

This continuation extends PR #1057 on
`fix/runtime-supervisor-remediation-20260927`. Its reviewed parent is
`9809ba0842e372783ea131038592bc841631606b`; the observed main is
`a126987b84737dbc2ee2592442a314117bddb4a2`. It does not import other convergence
branches, change branch protection, or authorize a merge or release.

The parent already contains the recovery signer, operator client, Agentd
executable prerequisite, instance-lock lifetime, blocking owner lane, immutable
read observations and timing counters. Those are preserved, not claimed as new
work here. Their native execution remains a separate prerequisite.

`IMPLEMENTATION_MAP.sourceBase` remains historical provenance. A tracked source
file cannot contain its own final commit hash. Candidate SHA, ordered merge
parents, tree and current source blobs are bound in external execution receipts.
A parent receipt must never certify a child commit.

## Gaps addressed by this continuation

### Default-build authority denial

Library unit tests compile with `cfg(test)`, which deliberately enables the
supervisor authority qualification seam. They do not prove that a default
product library or daemon rejects a runtime-supplied verifier.

`tests/default_authority_denied.rs` instead links the normal library and launches
the actual `CARGO_BIN_EXE_hepta-supervisord` without production features. Both
cases require the specific `ProductionAuthorityFeatureDisabled` outcome before
fleet creation. The binary case supplies syntactically and cryptographically
valid public keys and verifies that the keys are unchanged. An unrelated key
parse, filesystem or startup error is not an acceptable substitute. The process
has a bounded observation deadline and an owned kill/reap guard.

The deterministic public fixture key is test material, not an installed trust
anchor. These two Rust tests have been written but not executed in the editing
container.

### Exact binary/test identity

The old product plan required six key-loader test names and an aggregate
minimum. That alone did not require every signer, pair and durable-handoff case
to appear. Names were also not bound to their nextest binary IDs.

The v2 plan requires 19 explicit production-profile binary/test pairs: six
verifier-key tests, nine recovery-signing tests, one daemon process test, two
paired-process tests and one physical writer-handoff test. The default product
profile requires nine: six verifier-key tests, the daemon test and the two new
default-denial cases. Both library profiles retain all 15 owner, cancellation
and read-observation requirements.

A test name from another binary, aggregate count alone, duplicate terminal pass,
retry, flaky/leaky result, failed or missing summary, or a required skipped case
cannot satisfy the plan. Successful slow tests are recorded separately; this is
not a target-host latency qualification. The command fixes reporter verbosity,
turns retries off, suppresses successful test stdout, and retains all independent
tests after a failure. The raw log remains available on failure.

The parser follows the pinned nextest 0.9.103 human reporter. A reporter upgrade
requires reviewed parser fixtures. It validates trusted CI output consistency,
not authenticity against a malicious same-user runner or test executable.

### Evidence parsing and local file custody

JSON parsing rejects duplicate members at every nesting depth, non-finite
constants and overflowing float literals. Exit codes, schema versions, counts
and clean-worktree booleans are type checked rather than accepting Python's
`False == 0` equivalence.

Evidence reads use bounded, nonblocking, no-follow regular-file descriptors,
check inode identity and single-link status, and reject observable changes
between open and completed read. Symlinks, hard links, FIFOs, oversized sparse
files, replacement and growth are covered by negative fixtures. Parent directory
custody remains the trusted runner/operator's responsibility.

Records bind source/base/tested SHA, lane, run/attempt, exact command, unchanged
Git identity and raw log hash. All seven suite records must exist. The source
binding inventory includes the Rust workspace and its dependencies, not only
the supervisor crate. The assembler requires the exact ordered-parent synthetic
merge and recomputes its tree. It does not mutate implementation provenance.

A receipt is written outside the checkout with exclusive creation and file and
directory synchronization. An I/O failure remains a failed workflow; the mere
presence of a file, including one left by an interrupted publication, is not
acknowledgement. Consumers must require the exact successful job/check and raw
records in addition to the receipt. This is not external immutable retention.

## Required execution matrix

The reusable workflow dispatches these independent suites in each applicable
Linux/macOS source-head and deterministic base-merge lane:

| Suite | Evidence requirement |
| --- | --- |
| format | Read-only supervisor formatting, exact exit zero. |
| default | Library lifecycle fixtures, including 15 mandatory owner/read cases. |
| default-products | Normal library and daemon denial plus key and daemon tests; nine mandatory cases. |
| production | Explicit production-authority library profile; 15 mandatory owner/read cases. |
| products | Explicit production-authority process/signing/handoff profile; 19 mandatory cases. |
| lint-default | Strict lint of the default library, daemon and default-boundary integrations. |
| lint | Strict production-profile all-target lint. |

Every suite remains eligible after a peer suite fails, provided setup succeeded
and the run is not cancelled. There is no failure-to-success fallback. The final
fan-in rejects failed, cancelled, missing and applicable skipped results.
Nonapplicability can only acknowledge an explicit successful scope decision and
an actually skipped native lane; it does not produce native execution evidence.
Helper and policy-test changes themselves trigger the qualification path.

## Evidence actually obtained

In the editing container, the following command executed successfully:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_hepta_supervisor_ci \
  scripts.test_hepta_supervisor_evidence \
  scripts.test_hepta_supervisor_workflow
```

Result: **56 passed, zero failed, zero skipped**. These are Python policy,
filesystem and workflow-wiring regressions with synthetic runner transcripts.
The workflow fan-in shell was also executed over all 100 combinations of scope,
applicability and native result represented by its fixture table. Neither result
is Rust execution, a live process qualification, or independent acceptance.

The editing environment has no Rust toolchain and cannot resolve the GitHub
host for a native clone/build. No Rust, rustfmt, Clippy, default-daemon integration,
full receipt-assembly execution or target-host outcome is asserted here. Actual
source/base-merge Actions results must be read for the resulting commit; queued
or running jobs are not passes.

## Evidence classification and remaining gates

Do not overstate the existing tests: `paired_process_product` uses real OS
processes backed by a test-executable child fixture, not a deployed Agentd/Matrixd
product pair. `writer_handoff_production` exercises a real durable memory writer
but uses `AllowVerifier`, not an external authority distribution ceremony. The
256-observation test is not a 256-process mixed-load test.

| Requested stage | Remaining completion evidence |
| --- | --- |
| Trusted main | Green exact candidate CI required, Architecture required, Agentd and Supervisor qualification; resolve native formatting/lint/manifest/projection failures; merge without bypass and recheck the resulting exact main. |
| Production control chain | Full named caller -> pinned verifier -> real process -> durable state -> audit path; closed public writer API/permission inventory; independently provisioned keys and rotation/revocation/recovery drill. The existing CLI and signer are source components, not proof of this chain. |
| Concurrency | Per-agent mutation/tick ownership and short global registry commit coordination. The existing mutation worker remains serialized and whole-fleet observation refresh/startup I/O remains. Obtain actual 256-process isolation and latency distributions. |
| Target hosts | Final deployment artifacts, not merely source trees, on named Linux/macOS hosts through SIGKILL, ENOSPC, torn writes, directory fsync, PID/lease reuse, drain, restart budget, upgrade/rollback, permission failures, service-manager restart and soak. |
| Independent acceptance/release | Separately identified security and operator reviewers, recorded recovery exercise and independently checked artifact SHA-256. Patch-author fixtures cannot issue this acceptance. Activation and release remain false. |

The v2 receipt explicitly leaves deployment qualification, independent
acceptance, production activation and release false. Test-source presence,
receipt-parser success, CI execution and deployed-product acceptance are
separate claims.
