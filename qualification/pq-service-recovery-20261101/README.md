# PQ service continuity: FinalUse and AuthBus recovery controls

## Later CI follow-up

The execution phases below were published in commit
`7ff91a4368bc110c35da789b16916e046f79b42c`. A later
[two-test-file follow-up](followup/README.md) repairs the newly introduced
helper's strict-Clippy errors and the Windows raw-file-read lifecycle, preserving
all security assertions. It records 269 fresh Linux library test successes,
the remaining failed strict-Clippy command and the earlier hosted CI failures.
Those results have separate source identities and must not be combined into a
claim that full CI, original native pressure or whole-chain PQ has passed.

## Source and scope

The baseline is Hepta PQ PR #4368, commit
`a575cf03e2bc871a2f48021859c03ace806421c8`, tree
`980cb998c894ee1366098c099de3bbdc0abeb51f`. The first local commit adds sequence
controls to the existing authorization owners. A separate production change
repairs the owner-policy rollback reproduced by those controls. Cargo.lock,
cryptographic providers, message-signature profiles and resource limits retain
their baseline contents.

The baseline Agentd and Evidence library-test targets imported
`pretty_assertions` in five test modules without declaring that dependency.
Those imports are removed;
Rust's built-in `assert_eq!` executes the same assertions. This repairs the
test build without changing dependency versions or assertion requirements.

The acceptance question is whether a legitimate PQ operation can complete
after rejected requests and after reopening the durable owner, while previously
revoked identities and consumed nonces remain unusable. A rejection-only test
does not answer that question.

This is bounded owner/adapter evidence. It does not qualify the complete Cell-v2
entry from PR #4497, a paired Chain source, RunStart/ObjectiveStart migration,
public network operation, independent deployment custody, or whole-chain
quantum resistance.

## Added sequence controls

### Durable FinalUse owner and consumer entry

`final_use_pq_recovery_tests.rs` exercises the actual `FinalUseAuthority` and
`deliver_final_use_with_witness` implementation:

1. Reject an actual Ed25519 grant, an expired signed PQ grant, an old authority
   epoch, and a mismatched binding. Compare both durable files, capacity and
   frontier against their initial values.
2. Accept the unchanged legitimate PQ request and enter its original consumer.
3. Revoke that grant. Reject it and accept an independently signed new grant.
4. Restore both local files (`authority.json` and `authority.claims`) to the
   internally consistent old snapshot. Reopening must reject the mismatch with
   the retained external frontier.
5. Restore the actual current files. Reopening must preserve the two spent
   nonces and the revocation. A third fresh grant must enter the consumer,
   bringing the spent-nonce count to three.

The frontier in this particular test is the repository's existing in-memory
external-frontier fixture. It demonstrates the owner's conditional behavior
when that frontier survives; it is not evidence of an independently deployed
trust anchor.

### Actual Unix FinalUse authorizer

The existing native Unix test now serves seven responses through the original
issuer socket, clock client, frontier client and `UnixFinalUseAuthorizer`:

| Response | Expected result |
| --- | --- |
| Valid ML-DSA grant | Consumer entry; one nonce consumed |
| Classic schema with an actual Ed25519 signature | Rejected; frontier unchanged |
| PQ schema with an actual Ed25519 signature | Rejected; frontier unchanged |
| Replayed request challenge | Rejected; frontier unchanged |
| Signed grant expired at the current clock value | Rejected; frontier unchanged |
| Fresh valid ML-DSA grant after those failures | Consumer entry; two nonces consumed |
| Fresh valid ML-DSA grant after reopening the authorizer | Consumer entry; three nonces consumed |

Every rejection also checks the spent-nonce count. Reopening checks exact
frontier equality before the next request. The final external frontier must
equal the actual durable owner's frontier. The signer and verifier use the
pinned native provider; this test is not an independent cryptographic
implementation comparison. Local service fixtures are not independent
operators or production key custody.

### Agentd text admission and durable dispatch

The existing Agentd fixture now permits explicit key generations. The new
control drives the real producer, SQLite evidence/outbox, replay checkpoint,
issuer floor and dispatcher:

1. Admit a PQ message and acknowledge its dispatch.
2. Persist revocation and reject a subsequent request. Removing the revoked
   flag at the same epoch must still fail, including on owner reopen.
3. Install a legitimate new PQ key at the next epoch. Reject the old signed
   request, admit the new request, reopen the evidence owner and acknowledge
   dispatch. An exact retry must not dispatch a second copy.
4. Restore the old owner configuration and reject it against the durable floor.
   Restoring the current configuration must allow another new message to be
   admitted and acknowledged.

The queue transport uses the existing failure-injection fixture. This is not a
full App Server/model execution or a proof of resistance to rollback of every
external state component.

### Agentd/App Server product entry

`authbus_text_product.rs` retains its classical control and adds the PQ profile
to the same process harness. The test producer uses `sign_authbus_text_pq` and
an explicit schema-2 public-key registration. The original evidence owner is
bound to the selected profile before its initial checkpoint is captured.

A malformed signature is first rejected by the real daemon. The unchanged
valid request must then pass the ordinary control RPC, durable queue and App
Server, produce exactly one HTTP model request containing the signed text, and
persist a completed turn. Exact retries, later bad signatures, disallowed
threads and revoked authority must not produce another model request. The
model endpoint is the repository's HTTP fixture; this validates actual process
and transport behavior, not model quality or a Cell installation.

The native run exposed a separate active entry-point defect before thread
creation: filesystem helper re-execs inherit a reduced environment, but Agentd
required daemon-only environment variables before reaching helper dispatch.
The repair extracts the existing centralized helper-only dispatch in `arg0`
and calls it before Agentd configuration. Helper recognition and implementation
are unchanged. Normal daemon startup still establishes its private home before
`.env`, PATH aliases and runtime threads. No sandbox permission or daemon
environment is added to the helper.

## Reproduced owner-policy rollback and repair

Against the exact original production source, removing a thread from the owner
file rejected the legitimate signed request. After reopening against the actual
SQLite owner and retained external checkpoint, restoring the old same-epoch
owner file admitted that same request as `Queued`. The native regression failed
twice under nextest's retry policy; this is an admission result, not an inference
from a missing field. Key, revocation and clock floors alone did not bind the
thread-permission policy.

The repair adds a domain-wide monotonic `policy_revision` and canonical policy
digest. The digest includes Agent identity, issuer identity, public key, key
generation, revocation and the sorted thread-ID set. The issuer and policy pin
share the same SQLite write transaction. The new commitment participates in
the original AuthBus external checkpoint handshake, including pending recovery.
An earlier policy, changed contents at the same revision, or old issuer file
cannot reset it. Strictly newer revisions can intentionally remove or add
threads; the positive recovery test finishes three ordinary dispatches.

PQ configuration requires an explicit nonzero revision. Classical configuration
retains its prior format. A used PQ store with no policy record refuses first
pinning instead of treating the new empty migration table as a fresh authority.
Authenticated in-place migration for that older domain remains an open task.
The SQL migration extends the existing lineage without modifying any reserved
migration. No checkpoint is invented from a restored image.

The policy is committed only once the host reads and checkpoints it. Existing
snapshot-versus-queue timing semantics remain: already accepted work is not
cancelled by later revocation. The outside-home checkpoint file must be retained;
this is not proof of an independently deployed witness. The separate general
`EvidenceRecoverySnapshotV1` is not promoted into a complete-state commitment by
this change; these tests use the mandatory text ingress's AuthBus checkpoint.
Generic Evidence issuer-only APIs retain their separate contracts; the complete
text-policy pin is enforced by the actual `TextIngress` adapter, and is not
claimed as universal permission enforcement for every Evidence caller.

The downgrade control restores a valid schema-1 classical owner file, with its
real Ed25519 public key and no PQ-only revision field. The file independently
passes classical parsing. The already active PQ adapter rejects the profile
change, and a reopened owner rejects it against the immutable stored profile;
a correctly signed classical request cannot dispatch. Restoring a higher-revision
PQ policy permits another ordinary dispatch. A fresh classical configuration
retains its normal product control.

## Live-path boundaries

`hepta-agentd/src/lib.rs` selects `objective_runtime`; the old
`objective_ingress.rs` and `objective_dispatch.rs` files are not active modules
in this baseline. Their contents must not be used as evidence of the actual
runtime call graph.

The active `objective_runtime.rs` and `state.rs` still invoke
`require_run_start_v1()`. `RunStartAuthenticationV1` retains a 64-byte classic
signature, and the journal codec, conflict outcomes, producer and recovery
consumer remain a separate versioned migration. These controls do not remove
that refusal.

The active `smollm_cognitive_host.rs` obtains the selected artifact's
authentication profile, opens `UnixFinalUseAuthorizer`, and requires matching
profiles before opening inference control or loading the model. The explicitly
selected PQ authorizer is real production code. Passing its bounded adapter
test does not establish that another branch's complete Cell-v2 entry has
consumed it.

## Execution status

- Rust: the repository-pinned 1.96.0 toolchain; locked dependencies.
- Existing PQ FinalUse selection: 8 passed.
- Full contracts library with the new durable recovery sequence: 187 passed,
  zero skipped, using native Unix sockets.
- The first sandbox-only full contracts run passed 184 and failed three existing
  Unix service tests at `UnixListener::bind` with `EPERM`. The native rerun kept
  the same tests and assertions.
- Native Unix FinalUse authorizer selection: 5 passed; 58 unrelated tests
  filtered. The seven-response continuity and reopen sequence passed.
- Full Evidence library after the policy repair: 129 passed. One directly
  ignored subprocess-crash helper is invoked by its normal parent test.
- Full Agentd library after the policy repair: 232 passed. Six existing ignored
  cases were not run: five require exact paired Chain/fixture binaries, and one
  is the retained three-generation learning study. They remain outside this
  qualification. The owner-policy rollback regression, legitimate policy
  updates, reopened-state submission, issuer rotation and V1 refusal passed.
- The original owner-file rollback regression failed twice against unchanged
  production source, including the actual `Queued` result after restoration.
- After helper repair and the valid-classic-file downgrade control, the unified
  selection passed 22 tests: all seven `arg0` tests, ten AuthBus dispatch tests,
  and five PQ Unix FinalUse authorizer tests. The other 286 tests were filtered
  by the explicit selection; this was not a whole-workspace run.
- Actual product entry: all three tests passed, zero skipped. PQ and classical
  requests each completed the real queue/model/persisted-turn path; the missing
  trust control produced no model request.
- The retained first product run failed all three cases before thread creation: the
  Agentd binary required daemon environment variables before dispatching a
  sandboxed filesystem-helper re-exec. Both classical controls failed at the
  same point. The separate entry-point repair enabled the successful rerun;
  contracts or injected-queue outcomes were not substituted for that result.

The full Evidence and Agentd library suites ran after the policy repair and
before the later helper-dispatch repair and strengthened classical downgrade
control. The final code reran the affected 22-test selection and the three
product tests. These are overlapping selections, not additional disjoint
coverage; the full library suites were not all rerun at the final code head.

The scoped `just fix` command completed with exit code 0, without modifying any
Rust file. It was a normal Clippy run, not a `-D warnings` qualification. Existing
dependency and project warnings remain. Two `unwrap_used` warnings are in the
new test-only `sign_grant` fixture; no warning location falls on newly added
production lines. The complete output and the parsed warning inventory are
retained in the evidence bundle.

An intermediate full Agentd run passed 231 cases and failed the new reopened
state fixture because its original `AgentdState` still held an exclusive prompt
owner lock. Releasing that state before constructing its replacement repaired
the test lifecycle; the subsequent full 232-test run and final focused run
passed. This is distinct from the reproduced production permission rollback.

The first native host build stopped because `openssl-sys` could not discover
`pkg-config`. A subsequent attempt explicitly selected the already-installed
system OpenSSL headers and libraries. That attempt was interrupted when the
shared temporary target directory was removed during compilation; its failure
is an environment interruption, not a source failure. The retry uses this
task's isolated target directory.

The isolated single-job retry reached App Server compilation with 632 MiB of
disk remaining. Its own exec session was interrupted with Ctrl-C (exit 130),
an elevated process scan confirmed no remaining user of that target, and only
the stopped task's incremental compiler cache was cleared. The unchanged build
configuration then resumed from retained dependencies and completed the host
suite. This space-management interruption is not reported as a test failure
or a successful run.

A later focused test build was similarly stopped with 428 MiB free. The first
scoped Clippy run was stopped when the filesystem reported no available space.
Each interrupted log remains separate. After confirming that no compiler still
used this task's target, only its inactive incremental cache was removed. The
successful Clippy retry disabled incremental cache generation; the settings and
artifacts of the earlier successful native test runs were unchanged.

## Evidence identities

The [evidence manifest](evidence/manifest.json) records the commands, phase
boundaries, exact skip inventory and hashes of every retained log. Logs are
stored as lossless gzip files; their original and compressed SHA-256 values are
both recorded. The [source inventory](evidence/verified-source.json) binds the
changed Rust/SQL sources and selected unchanged owners, lockfile and toolchain
to local code commit `0c0f4a666a8a6d8c85f1ae8f67d11b72c5480a84`.

The five implementation/test commit identifiers in that inventory describe
local execution stages. They are not claims that those commits were published
remotely. A Git-data publication can have a different commit identity while
retaining the exact verified source bytes. Later qualification-document commits
do not change the runtime sources.

The [native artifact inventory](evidence/native-artifacts.json) records eight
retained Linux executables, their phase, SHA-256 and runtime linkage. The actual
Agentd executable used by the successful product run has SHA-256
`9d92350adbc46fbb92686fa04d758d7448d7d1880f6dcae3b11f0939902f636a`.
The earlier Contracts executable was in the subsequently removed shared target;
its successful raw log remains available, but that executable is not claimed as
a retained artifact. Large executable files remain in the execution workspace
and are not added to Git.

## Reproduction

Use the pinned Rust 1.96.0 tools and the repository's `just test` runner. On the
observed Linux executor, system OpenSSL was selected with
`OPENSSL_INCLUDE_DIR=/usr/include` and
`OPENSSL_LIB_DIR=/usr/lib/x86_64-linux-gnu`; no dependency version was changed.

```sh
just test --locked -p codex-hepta-contracts --lib
just test --locked -p codex-hepta-infer-worker-host --lib -E 'test(final_use_authorizer::pq)'
just test --locked -p codex-hepta-evidence --lib
just test --locked -p codex-hepta-agentd --lib
just test --locked -p codex-hepta-agentd --test authbus_text_product
just test --locked -p codex-arg0 -p codex-hepta-agentd -p codex-hepta-infer-worker-host --lib -E 'package(codex-arg0) | test(authbus_dispatch::tests) | test(final_use_authorizer::pq)'
CARGO_INCREMENTAL=0 just fix --locked -p codex-arg0 -p codex-hepta-contracts -p codex-hepta-evidence -p codex-hepta-agentd -p codex-hepta-infer-worker-host
```

The observed runs use one Cargo build job and the repository's existing
debug-free test build convention. No capacity or timing qualification is made
from these unit and adapter controls.
