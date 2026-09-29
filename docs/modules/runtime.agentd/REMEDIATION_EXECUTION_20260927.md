# runtime.agentd remediation execution record — 2026-09-27

## Scope and evidence boundary

This change extends PR #1025 on `work/runtime-agentd-remediation-20260926`.
Its observed parent is `6f9bc0d754ec2c9e6ee40ccd76172629eeda6735`. A fresh PR
read after the implementation commit confirmed the integration target as
`work/product-convergence-20260923`, not `main`. This supersedes the earlier
inconsistent metadata naming `integrate/agentd-product-sweep-20260829`. The
workflow covers both integration branch names; this change does not retarget PRs.
No production activation, branch-protection bypass, force update, or merge is
performed by this change. Resolve the commit containing this record for the
candidate SHA; do not treat the parent SHA as evidence for the new candidate.

Repository reads exposed inconsistent path/log snapshots. The control transport
edit was therefore based on the content-addressed blob
`e0dead7af43df1ed6565cedae0b31b730bc1152a`, whose Git blob hash was checked locally.
Historical workflow names, PR descriptions, and prior passing tests are not
substitutes for running the new candidate. The new workflow explicitly checks
out the PR head and rejects a different or dirty checkout.

## Implemented in this change

### Independent exact-head engineering workflow

`.github/workflows/hepta-agentd-exact-head.yml` adds Linux and macOS jobs for
owner libraries, native libraries, native process E2E, daemon process E2E,
product process E2E, strict Clippy, and the no-default-features profile. Matrix
fail-fast is disabled; there is no dependency from one suite to another. A
library failure cannot skip the independent E2E or Clippy jobs. Build failures
remain failures, not waived prerequisites. Source ownership/derived projections
and the receipt verifier tests run independently of the Rust matrix.

The workflow has no PR path filters. A supervisor-only, AuthBus-only, protocol,
workflow, dependency, or documentation change cannot silently evade this gate.
Push qualification covers main, this work branch, and the existing integration
branch. It does not alter the existing workflows or repository rulesets.
`Agentd exact-head required` is the aggregate check name, but **its name alone
is not branch-protection enforcement**. A repository administrator must verify
and configure the required-check rules on the integration/main branches.

### Executed-command and artifact-digest receipts

`scripts/qualification/agentd_exact_head.py` owns the suite command plan and
uses `cargo --locked`. Cargo JSON compiler-artifact output selects executable
paths; no assumed `target/debug/hepta-agentd` path is used. Current `HEPTA_*_BIN`,
legacy `*_EXE_PATH`, and supported `CARGO_BIN_EXE_*` aliases resolve to the same
built executable. Missing or ambiguous fixtures fail qualification.

Each receipt includes actual checkout SHA, expected SHA, run ID and attempt,
actual host OS/architecture, compiler identity, lockfile/runner/workflow SHA-256,
exact commands, exit codes, elapsed times, command-log SHA-256, and executable
SHA-256/size. Executables are rehashed after tests to detect mutation. A timed-out
subprocess group is killed and recorded with exit code 124. A receipt is written
after an error wherever the runner has started; an absent receipt is also fatal.

The aggregate requires all 14 OS/suite pairs from the same run attempt, all
commands successful, matching source digests and logs, and successful independent
jobs. It rejects duplicates, stale SHA, skipped/failed jobs, modified logs,
missing binaries' digest entries, unsafe log paths, symlinks, duplicate JSON
keys, oversized receipts, and non-finite JSON. A failed verification writes a
failure summary rather than leaving a previous success summary in place.

**Trust limit:** these are engineering integrity receipts, not signatures.
Executable bytes are hashed on the runner, not shipped in these log bundles;
`binary_evidence` explicitly says `digest-only-not-a-release-artifact`.
An adversary controlling the workflow can fabricate a self-consistent receipt.
Acceptance must also authenticate the GitHub run and approved workflow/source.
Release artifact provenance, signing, and independent acceptance remain separate.
`production_activation` is always false, including in a successful summary.

### Structured control-connection shutdown

`control_base.rs` now stops accepting preferentially on cancellation, observes
JoinSet results, and drains on normal shutdown **and accept failure**. Already
accepted requests get the existing frame-I/O budget (currently two seconds) to
finish. Unfinished tasks are then aborted and joined; timeout returns an error,
not a successful drain. Connection-task panic/unexpected cancellation reaches
the owner instead of being discarded. Client protocol/transport errors remain
isolated and produce a bounded diagnostic without logging request payloads.

The new `control_connection_lifecycle.rs` contains six regression tests: empty
drain, waiting for accepted work, isolated client error, bounded timeout with
permit reclamation, task panic, and unexpected task cancellation.

This is a **transport** drain, not proof of physical runtime cancellation. An
aborted connection must not trigger blind retry or a fabricated terminal
outcome. Reconcile the original durable operation identity. Outer supervisor
shutdown budgets must exceed the transport grace period; longer business
operations may still be indeterminate after the grace deadline.

## Validation performed during implementation

The local environment has Python and Git, but no Cargo/rustc and no working DNS
route to clone GitHub. GitHub connector reads/writes are available.

- Python unittest suite: 16 test methods passed, including adversarial subcases,
  subprocess failure, timeout/process-group termination, fixture alias binding,
  source-digest drift, and failed-job summary handling.
- Workflow YAML and matrix/command-plan consistency checked locally.
- Original transport file Git blob hash checked before editing.
- Rust regression tests and Clippy: added/required, **not executed locally**.
- Linux/macOS CI results for the commit containing this record: must be read from
  GitHub; this document does not predeclare a pass.

Synthetic unittest receipts are explicitly fixtures, not production or CI proof.

## Remaining closure gates

| Gate | Required evidence | Status at implementation |
| --- | --- | --- |
| Exact new candidate | All independent checks, no skipped required jobs; authenticated aggregate/run | Pending remote execution |
| Repeated main baseline | At least three consecutive main push qualification runs at the actual main candidates, without cherry-picked reruns | Not established |
| Canonical executor | Public control start -> current AuthBus capability -> durable admission -> physical start/interrupt/terminal -> same coordinator | Not demonstrated by this change |
| Current trust | Non-forgeable verified capability, issuer/epoch/generation/digest/expiry binding, revocation and replay negative tests | Requires code/evidence audit |
| Neuron lifecycle | Single owner, generation fence, recover/drain/retire and crash tests through daemon supervisor | Requires exact-candidate proof |
| Core isolation | Core builds without product-domain dependency graph, not merely with default features disabled | Still open |
| Production writer | Explicit opt-in profile only; current parent Cargo.toml already has `default = []` | Preserve; no new authority installed |
| Release provenance | Retained deployable bytes match tested digests, approved builder/workflow identity and release signatures | Not provided by digest-only receipts |
| Target-host faults/load | Platform-specific execution receipts below | Not executed |
| Independent acceptance | Named reviewer distinct from implementer; signed acceptance for exact release digest | Not performed |

A successful `--no-default-features` profile does not establish core/adapters
separation: the current Cargo manifest still has broad unconditional product
dependencies. Do not relabel that architectural gate as complete.

## Target-host qualification protocol

Run only on designated disposable hosts/filesystems, never by filling or
corrupting a production volume. Record source/release digest, host identity,
kernel/service manager, effective configuration, run/operation identities,
initial state, injection boundary, final durable state and audit receipts.

| Scenario | Injection and observation | Pass invariant |
| --- | --- | --- |
| Drain under load | Saturate 32 admitted control connections, request drain while physical turns are active | No new acceptance after fence; every task joined; ambiguous effects remain reconcilable |
| Backpressure | Exceed connection capacity, include slow readers/writers | Bounded descriptors/memory; deterministic overload or timeout; health remains observable |
| Agentd crash | Kill disposable daemon before/after durable admission, physical start, dispatch fence, terminal commit | No duplicate physical dispatch; no invented negative/success outcome |
| Worker crash | Kill disposable runtime worker during start, cancel and terminal delivery | Coordinator reaches evidenced terminal or indeterminate state, never silent success |
| Storage faults | Isolated disk full/read-only/fsync/rename errors and truncated state files | No acknowledgement before durability; fail closed or quarantine; preserve diagnostic evidence |
| Stale generation | Advance owner generation and replay old start/cancel/terminal requests | Old generation cannot mutate new owner; no acceptance based only on echoed request identity |
| Capacity/latency | Fixed workload, concurrency and hardware; retain histograms and resource samples | Declared target met without omitting failures; no monotonic leak |
| Soak/recovery | Sustained run/cancel/restart cycles with periodic faults | Stable resource bounds and complete reconciliation accounting |

Do not claim kill/fsync/ENOSPC coverage from a Python receipt unit test or from
an in-memory state transition test. Physical fault evidence is a separate gate.

## Operations, SLOs and rollback

Operational review must approve service-specific targets before activation.
Candidate targets (not measured guarantees): zero duplicate physical dispatch,
zero stale-generation mutation, zero acknowledged-but-nondurable admission,
control connection count <= 32, and no unbounded drain. Establish the health
latency and cancellation/terminal-observation percentiles from target-host
measurements; do not invent a universal latency number from unit-test timing.

Required telemetry work includes active/overloaded connections, operation
latency, stale-generation and trust rejections, drain timeouts, task panic,
indeterminate run count/age, durable-write failures, worker health, restart and
reconciliation counts. Alert immediately on durability/fencing failures and
sustained growth of indeterminate work. This document specifies required
telemetry; it does not assert that all exporters/alerts are installed.

On failure: close admission through the installed supervisor control interface;
retain the exact candidate identity, logs and state; reconcile original run IDs;
do not retry an operation merely because its connection timed out. A task panic
or drain timeout requires investigation, not conversion into a green receipt.

Before rollback: fence the current owner, stop admission, retain a durable state
snapshot and its digest, and verify the older binary can read the current state
schema. Never roll back state generations or signing epochs. Start the approved
previous release with a new owner generation, reconcile without redispatch, and
reopen admission only after readiness and trust checks. Unknown schema
compatibility requires recovery review, not an automatic binary downgrade.

Activation requires separately authenticated target-host and independent
security acceptance tied to the exact deployable artifact digest. This change
provides neither a production signer nor a way around that gate.

## 2026-09-28 instance-ownership and bounded-maintenance addendum

The active convergence line replaces the process-global runtime.codex installation slot with an explicit supervisor handle owned by the typed bootstrap, `AgentdConfig`, `AgentdState` and the required `RuntimeTasks` future. A handle is fail-stop after owner start, but separate handles do not share process state. All fallible trust, store and socket initialization precedes task ownership. This narrows lifecycle ownership without introducing a plugin registry or second supervisor.

Periodic reconciliation and terminal archival now run in a separately joined maintenance owner. Per-run lock waits observe cancellation, active directories are traversed through bounded deterministic cursor pages, archival remains witness-before-rename with directory synchronization, and shutdown accounts for reserved, queued, already-dequeued and running work before joining maintenance. Operational snapshots distinguish reservation, queue and running counts; queue and unresolved ages; recovery duration/lock wait; pending archive; persistence/shutdown failures; and admission rejection causes.

`DEPENDENCY_BOUNDARY.json` and its verifier classify the exact Cargo dependency inventory. They intentionally record `coreOnlyBuildEstablished=false` and `productAdaptersOptionalized=false`: an empty default feature set is not relabelled as core/product separation. The migration ratchet forbids changing durable history, authority semantics or the sole execution spine merely to make dependencies optional.

The exact-candidate workflow now uses immutable action revisions, real package and process-test names, current repository-owned projection checks, dependency/trust-boundary tests and a separate deterministic prospective-merge compile/test/lint job. The one-shot patch carrier and self-mutating apply workflow are removed after their source delta is integrated. None of these source changes claims target-host qualification, release provenance, independent acceptance, activation, promotion or release. Those gates remain false until the final exact candidate produces successful retained evidence.
