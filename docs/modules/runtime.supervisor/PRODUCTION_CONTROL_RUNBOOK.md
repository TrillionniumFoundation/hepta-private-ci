# Runtime supervisor production control and acceptance runbook

Status: implementation candidate; not a deployment approval.

This runbook is the operator-facing companion to `TECHNICAL.md` and
`RECOVERY_AND_QUALIFICATION.md`. For the choice between legacy abort and signed
terminal recovery, use the decision procedure below rather than interpreting
legacy abort as proof that a rollback completed. Source integration, execution
qualification, target-host qualification, independent acceptance, activation,
and release are separate facts.

## 1. Named control path and actual authority boundary

The named source-level operator caller is the existing binary
`hepta-supervisor-intent-recovery`, now with `inspect-production` and
`submit-production` subcommands. It calls `SupervisordClient`; it does not open
release-state files for writing. The intended release-state writer is
`hepta-supervisord`, using the existing fleet owner lock, control-fence CAS,
release transaction and signed-intent journal. The offline signing binary is
`hepta-authority-signer`; it never starts the daemon, writes its state, or creates
keys.

The resulting source path is:

```text
operator-reviewed request + externally held signing key
    -> hepta-authority-signer
    -> reviewed signed method file
    -> hepta-supervisor-intent-recovery submit-production
    -> SupervisordClient / supervisor control protocol v2
    -> daemon CAS and independently configured authority verifier
    -> existing release transaction / signed intent
    -> observed durable mutation state
```

This is a named caller, not proof of an exclusively controlled deployment
writer. Fleet filesystem access and same-UID process isolation still require
explicit deployment controls. An advisory owner lock is not a security boundary
against another process that can write the same files. The verifier keys, fleet
root, operator credentials and managed children must have a reviewed ownership
and sandbox policy. No new in-repository key or blanket caller privilege is
introduced by this change.

## 2. Build and trust-anchor prerequisites

Use the repository's approved build wrapper and exact candidate toolchain. The
production-authority feature must be deliberately enabled for the supervisor
binary. The default build remains authority-denied. A production build alone is
not a production activation.

The preferred production verifier configuration is one externally distributed,
public-only authority bundle pinned by its exact digest:

```text
--authority-bundle ABSOLUTE_PUBLIC_BUNDLE_FILE
--authority-bundle-sha256 APPROVED_BUNDLE_SHA256
```

The bundle binds the grant signer ID/epoch/key and H7 signer ID/epoch/key in one
versioned object. The daemon validates the bundle's internal digest and requires
the operator-supplied exact bundle digest before constructing either verifier.
The bundle contains no private signing material and does not select a release.

The direct six-option verifier tuple remains a compatibility path:

```text
--grant-verifier-key ABSOLUTE_PUBLIC_KEY_FILE
--grant-signer-id APPROVED_GRANT_SIGNER_ID
--grant-signer-epoch APPROVED_GRANT_SIGNER_EPOCH
--h7-verifier-key ABSOLUTE_PUBLIC_KEY_FILE
--h7-signer-id APPROVED_H7_SIGNER_ID
--h7-signer-epoch APPROVED_H7_SIGNER_EPOCH
```

Use exactly one configuration form together with `--fleet-root`. The public
verifier material must come from an independently authenticated external custody
process, not from a request field, fixture seed, repository-generated key, or
self-approved receipt. Neither form establishes a key-distribution service by
itself.

Before deployment, the external custodian must provide a versioned manifest
binding signer ID, signer epoch, key fingerprint, purpose, approved environment,
activation/revocation dates and approver identity. The installer must verify this
manifest out of band, stage immutable public-key files, validate file and parent
directory ownership, and record the installed fingerprints and daemon artifact
digest. No such external custody receipt is claimed in this branch.

For rotation or revocation, close admission and preserve unresolved intents,
install the independently approved successor key/epoch bundle, restart under the
normal daemon ownership procedure, then re-observe state. A daemon restart
changes its epoch: requests signed for the previous observed authority context
must not be silently rewritten or retried. Re-sign only after a new review.
Revocation must not leave the old trust root accepted indefinitely. Emergency
revocation and restoration of availability require a witnessed drill before
activation.

The private-key loader accepts exactly 32 raw bytes or 64 hexadecimal characters.
On Unix it rejects relative paths, symlinks, non-regular files, group/world
permissions, a different effective owner, and an inode changed during open. It
uses the opened descriptor for the decisive checks. Parent directory integrity
remains a custodian responsibility. `--key-fd` duplicates the descriptor with
close-on-exec; it preserves descriptor ownership but consumes the shared file
offset. A pipe writer must close its end; a byte limit is not an input timeout.

## 3. Observe before signing

Read-only online inspection is:

```sh
hepta-supervisor-intent-recovery inspect-production "$SOCKET" "$AGENT_ID"
```

`SOCKET` must be an absolute path. The output contains `snapshot`,
`production_mutation`, and `release_selection`. The caller reads the complete
bundle twice and rejects changing observations. This reduces accidental mixed
observations but is not an atomic snapshot or an authorization proof. The daemon
must revalidate the submitted fence and exact durable witnesses before acting.

Retain the original observation and the current control fence. Do not invent
control revisions, epochs, lifecycle generations or SHA-256 values. Do not
substitute a release name for immutable release-byte identity.

## 4. Recovery decision procedure

Use signed terminal recovery only when the current durable release outcome is
independently observable and agrees with a terminal release transaction. The
signer request operation is `production_recovery`. It contains every field:

```text
signer_id, signer_epoch, agent_id
grant_sha256, intent_sha256, release_transaction_sha256
observed_release, observed_manifest_sha256
observed_agentd_sha256, observed_matrixd_sha256
outcome, expected_lifecycle_generation, authority_epoch
issued_at_unix_seconds, expires_at_unix_seconds
```

`outcome` is `committed` or `rolled_back`, not an instruction to guess or force
that outcome. `observed_matrixd_sha256` is null only when the observed release
has no Matrix companion. Use the existing domain-separated recovery schema v1.
Do not reuse a production-grant signature for a recovery decision.

The existing maximum signed lifetime is 86,400 seconds. Prefer a substantially
shorter approved ceremony window. Times are explicit Unix seconds. The verifier
rejects future-issued and expired decisions, wrong signer/key epoch, wrong agent,
authority epoch or lifecycle generation, and every mismatched intent,
transaction, manifest or executable digest.

The offline invocation is:

```sh
umask 077
hepta-authority-signer --sign \
  --key-file "$EXTERNAL_KEY_FILE" \
  --request "$REVIEWED_REQUEST_FILE" > "$SIGNED_RESPONSE_FILE"
```

The response is tagged `production_recovery` and contains a `decision` object.
The request and response paths in the ceremony should be new private files;
retain their digests in the external audit system. Never put a private key in a
repository, issue, workflow input, log or acceptance attachment.

## 5. Submit the reviewed method without automatic retries

The submission file is an existing `SupervisordMethod`, not a second protocol and
not a complete `SupervisordRequest` wrapper. A recovery method has this shape:

```json
{
  "type": "resolve_production_recovery",
  "fence": "REPLACE_WITH_THE_OBSERVED_CONTROL_FENCE_OBJECT",
  "decision": "REPLACE_WITH_THE_SIGNED_DECISION_OBJECT"
}
```

The strings above are intentionally non-executable placeholders. The actual
values must be typed objects from the reviewed observation and signed response.
For an ordinary signed upgrade or rollback, use the existing `signed_upgrade`
or `signed_rollback` method with its exact `fence`, `grant`, and `h7_envelope`.
The caller refuses unsigned lifecycle methods on this submission path.

```sh
hepta-supervisor-intent-recovery submit-production \
  "$SOCKET" "$REVIEWED_METHOD_FILE" --submit
```

The method file must be absolute, regular, bounded and non-symlink; on Unix its
opened descriptor must belong to the effective user and not be writable by
other users. It is parsed with the existing strict protocol types. Private
signing keys and verifier configuration are not accepted in the method.

The command sends one request. It does not retry after a timeout or connection
loss. A lost response is an unknown observation, not proof of non-application.
Inspect durable state and compare the exact grant, intent, release-transaction
and recovery-decision identities before deciding whether another operation is
needed. A changed fence requires a new observation and review, never an automatic
update to a previously signed request.

Signed upgrade/rollback output uses the canonical mutation-accepted payload.
Acceptance is not terminal completion. Re-query `production_mutation` until the
existing durable protocol exposes the terminal state or recovery-required state.
Recovery output includes the submitted decision digest and returned durable state.
Retain the original request, signed response, submission result and subsequent
observation together. A caller's stdout is not a substitute for daemon-owned
durable evidence or an independent audit receipt.

## 6. Legacy inspect and abort are not signed success recovery

The existing offline commands remain available:

```sh
hepta-supervisor-intent-recovery inspect "$RUN_ROOT"
hepta-supervisor-intent-recovery abort "$RUN_ROOT" "$EXACT_INTENT_SHA256"
```

Use this conservative path when the effect is ambiguous and cannot be proved to
have committed or rolled back. First close admission and fence the ambiguous
work under the established operator procedure. Abort writes the existing
exact-intent-bound directive; it does not assert that a predecessor is active,
roll back external effects, authorize a new release, or convert uncertainty into
success. Do not manually edit or delete intent/restart/transaction files to make
the daemon ready. A failed or conflicting abort requires re-inspection.

Online signed recovery and offline abort must not be run concurrently. They are
different terminalization procedures with different evidence requirements, not
fallback implementations of the same successful operation.

## 7. Candidate execution evidence

`blocking-ci.yml` calls `hepta-supervisor-qualification.yml`; its terminal result
is a required dependency of `CI required`, not an allowed skipped dependency.
The reusable workflow explicitly selects applicability. For applicable changes,
Ubuntu and macOS each execute source-head and prospective-merge lanes on PRs;
main pushes execute the exact landed source on both platforms. Native commands
are not replaced by an identical-tree shortcut in this supervisor workflow.

Formatting, the default library, the production-authority library, product tests
and strict lint run independently after successful prerequisite setup. One suite
failure does not suppress the other suites. A missing, failed, cancelled or
applicable skipped lane still fails the aggregate. The product suite includes
real-process fixtures; it is not automatically a deployed product or target-host
qualification.

`scripts/hepta_supervisor_ci.py` delegates execution to the existing bounded
`hepta_ci_exec.py`. Before producing `qualification.json`, it checks exact source,
base, tested commit, merge parents/tree, run ID and attempt, clean before/after
identity, reviewed command, actual return codes, raw log length/digest and
re-parsed passing test counts. Raw records and logs are retained on failures too.

The receipt binds the exact implementation-map blob and current source blobs.
Historical `IMPLEMENTATION_MAP.sourceBase` remains provenance and is copied as
`implementation_source_base`; it is not relabeled as the currently tested SHA.
The exact candidate identity lives in the external run artifact, avoiding a
self-referential commit hash. Only `scoped_execution_complete` can become true.
Deployment qualification, independent acceptance, activation and release remain
false. Candidate-generated CI records are diagnostics, not independently trusted
approval signatures.

## 8. Unclosed concurrency and target-host qualification

This change does not replace `Mutex<Supervisor<D>>` with per-agent actors. That
migration must preserve per-agent command ordering, monotone generations,
release/intent commit ordering, shutdown ownership and cross-agent release
coordination. Read snapshots must carry a publication revision and staleness
policy; a fast cached status must never become authority for a mutation.

The replacement requires bounded per-agent queues, a short coordinator, no
filesystem/process waits inside that coordinator, and explicit admission during
shutdown and recovery. Tests must inject a stalled agent while continuously
measuring another agent's reads, mutation admission and tick progress. Record
queue depth, lock wait/hold, tick lateness and p50/p95/p99 distributions for 256
instances under mixed reads, drains, crashes, upgrades and restarts. No scale or
isolation result is asserted until actual execution artifacts exist.

The deployment operator must qualify the final executable digest on each declared
production target. Linux and macOS are distinct targets; hosted CI on either one
is not evidence for an unspecified production filesystem or system manager.
Windows support is not added here. Required fault classes are:

| Fault boundary | Required observation |
| --- | --- |
| Daemon SIGKILL and system-manager restart | Exact owner/epoch recovery; no duplicate writer or blind resume |
| Spawn before lease publish; PID reuse | Exact process identity; never signal an unrelated process |
| Torn intent/restart/transaction writes | Reject corruption; preserve acknowledged durable prefixes |
| ENOSPC, failed rename, failed directory fsync | No false durable acknowledgement or success promotion |
| Flapping process and clock rollback | Bounded durable restart budget without free retries |
| Drain while durable work is outstanding | No drain acknowledgement before the protocol's terminal fence |
| Upgrade/rollback crash at every commit boundary | One recoverable terminal outcome or explicit uncertainty |
| Artifact replacement, permission or key changes | Reject mismatched immutable bytes and authority context |
| Full-load mixed traffic and a stalled peer | Measured tail latency and per-agent isolation |
| Sustained soak on named deployment hardware | Recorded duration, load, resource curves and unresolved faults |

For each run retain host/OS/kernel/filesystem identity, toolchain, feature set,
artifact SHA-256, source/base/tested SHA, seed/workload, fault location, exit status,
raw logs, durable snapshots before/after, and operator identity. A blank matrix,
fixture checksum or newly written test is not an execution receipt.

## 9. Independent acceptance and release

The author of this patch must not sign as the independent security reviewer or
operator. Required external evidence is an independently reviewed threat model,
a witnessed recovery drill, acceptance of the final qualified binary digest,
and a named operator's decision for a specific environment. Freeze the accepted
protocol/schema compatibility set and record rollback prerequisites.

Only after all applicable exact-head required checks, target-host qualification
and independent acceptance are successful may a separate authorized deployment
operation change activation/release state. This branch does not perform that
operation, claim an external custodian exists, or manufacture approval receipts.
