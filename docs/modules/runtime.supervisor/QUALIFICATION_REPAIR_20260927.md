# Supervisor / Agentd qualification prerequisite repair

## Observed source and failure

The examined main candidate is `a126987b84737dbc2ee2592442a314117bddb4a2`.
Agentd process qualification run `36092481073`, Ubuntu job `107937631444`,
reached 361 library tests: 359 passed, two failed, and zero were skipped.
The failures were:

- `cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start`
- `real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`

Both diagnostics reported that neither `HEPTA_AGENTD_TEST_BIN` nor a built
`hepta-agentd` sibling was available. `--lib` compiles library test executables;
it is not evidence that the separate product daemon binary has been built.
The missing-binary check must remain an error. This finding does not establish
that all later runtime, lint, projection, or platform checks will pass.

## Repair and evidence contract

The process workflow now builds the default-feature product daemon before
product-boundary library tests. `hepta_agentd_product_prerequisite.py`:

1. Requires the exact clean candidate and records its tree, lockfile, and
   toolchain-manifest digests before building.
2. Runs a fixed `cargo build --locked -p codex-hepta-agentd --bin hepta-agentd`
   command with Cargo's JSON artifact messages. It does not enable production
   authority or the qualification write feature.
3. Accepts exactly one regular executable from the expected manifest and target
   directory, plus a successful `build-finished` event and exit code zero.
   It never guesses a sibling executable or accepts an old binary by existence.
4. Records the executable path, byte count, SHA-256, command, bounded raw logs,
   run ID/attempt, and unchanged source identity after the build.
5. Publishes receipts through temporary-file fsync, atomic replacement, and
   directory fsync. A crash may leave a `running` record, never a false pass.
6. Exports `HEPTA_AGENTD_TEST_BIN` only after successful receipt publication.
   Timeouts, output overflow, source drift, wrong manifests, and missing
   artifacts fail closed. Build process-group cleanup is bounded.

Build outputs and evidence live outside the checkout. Logs are limited to
16 MiB per stream, and command execution defaults to 2,700 seconds. This is a
POSIX CI build helper, not an isolation sandbox for hostile compilers: a child
that deliberately escapes its process group is outside this helper's guarantee.
A build receipt is not a signed trust root and does not authorize deployment.

Independent test-suite steps can run after a peer suite fails, provided their
product prerequisite succeeded. A previous failure remains a job failure.
The existing exact-tree native-sharing planner and strict final fan-in remain
unchanged. A tree-equivalent shared lane does not acquire a new build receipt.
The dedicated supervisor workflow's own source/base-merge evidence is separate.

Trigger coverage now includes supervisor documents, workspace manifests,
lockfile/toolchain/configuration inputs, paired-process protocol owners, the
prerequisite helper, and its regression tests. This expands the Agentd lane;
it is not a claim that every workflow's complete dependency closure is proved.

## Validation performed for this patch

The local Python helper and workflow-wiring suites passed 23 tests with zero
failures and zero skipped tests. They cover orchestration, negative artifact
binding, process time/output bounds, source drift, receipt publication, workflow
ordering, retained test suites, and trigger wiring. Synthetic executables and a
synthetic Git checkout are used in these tests; no Rust product test is implied.

Rust/Cargo and target-host execution were not available in the editing
container. Linux/macOS native outcomes must come from the pushed candidate's
real Actions runs. Do not copy this local test count into native qualification.

## Remaining completion gates

| Phase | Required evidence still to obtain |
| --- | --- |
| Trusted main | Successful exact-candidate CI required, Architecture required, Agentd and supervisor qualification; fix remaining formatting/projection/lint failures; then merge and recheck exact main. |
| Production control | Verify the existing recovery-signer work, named production caller and writer enforcement, externally provisioned trust keys, and full caller-to-audit recovery tests. Documentation or a key file alone does not establish this. |
| Concurrency | Implement and verify per-agent ownership, lock-free/read snapshots, bounded I/O workers, short global commit coordination, and measured 256-agent isolation. No concurrency redesign is claimed by this patch. |
| Target hosts | Actual daemon binaries and final artifact hashes exercised through SIGKILL, ENOSPC, torn writes, directory fsync, stale PID/lease, restart budget, drain work, upgrade/rollback, permissions, service-manager restart, and soak scenarios. |
| Independent acceptance | An independently identified reviewer/operator must run the threat-model review and recovery drill, verify the deployment artifact, and record acceptance. The patch author cannot self-issue that acceptance. |

Keep implementation provenance (`sourceBase`) separate from current execution
identity. Current candidate SHA/tree belongs in execution receipts, not in a
self-referential source commit. No production, deployment, acceptance,
activation, or release declaration is raised by this repair.
