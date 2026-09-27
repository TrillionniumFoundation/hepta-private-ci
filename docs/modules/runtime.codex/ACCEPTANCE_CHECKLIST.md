# runtime.codex acceptance checklist

This checklist is fail closed. Mark an item complete only with current evidence
for the exact candidate named in the acceptance record. `N/A` requires a written,
independently reviewed rationale; it must not be used to erase a failed gate.

## A. Candidate identity

- [ ] Exact repository, source commit and source tree are recorded.
- [ ] Ordered synthetic-merge base/source parents and merge tree are recorded.
- [ ] Worktree cleanliness was checked before and after every command.
- [ ] Binary, lockfile, toolchain, configuration and implementation-map digests
      are bound to the candidate.
- [ ] No mutable branch name is used as evidence identity.

## B. Repository source qualification

- [ ] Runtime binaries build from the exact candidate with `--locked`.
- [ ] Adapter terminal/correlation tests pass.
- [ ] Durable local journal and restart/no-replay tests pass.
- [ ] Agent protocol and lifecycle tests pass.
- [ ] Worker-host authority, cancellation, deadline, owner-loss and cleanup tests
      pass.
- [ ] Fence-aligned crash-matrix tests pass with the declared minimum count.
- [ ] Signed quarantine protocol tests pass with the declared minimum count.
- [ ] Real Agentd/App Server product composition test passes against the
      controlled provider and proves one physical request.
- [ ] Model-only tool topology test passes.
- [ ] Strict Clippy passes with `-D warnings` for every declared package/target.
- [ ] Formatting passes without source mutation.
- [ ] Exact-head receipt status is `passed`.
- [ ] Ordered synthetic-merge receipt status is `passed`.
- [ ] Every command log and receipt is retained and digest-bound.
- [ ] GitHub provenance/attestation verifies for the retained receipt bytes.

Any missing, skipped, cancelled, timed-out, zero-test, malformed, stale or
nonzero command keeps this section failed.

## C. Effect-entry and recovery invariants

- [ ] Final owner/ingress, context, cancellation, deadline, revocation and
      `VerifiedUseToken::enter` checks occur before the server-owned fence.
- [ ] Agentd accepts the exact effect-entry CAS from only `ContextAttached`.
- [ ] Only a fresh, exact, non-idempotent fence acknowledgement grants one send
      permit.
- [ ] Idempotent, lost or mismatched fence acknowledgement grants no send.
- [ ] Post-fence abort is impossible at the owner.
- [ ] Local abort proof is non-cloneable, non-serializable and destroyed when
      the fence may have committed.
- [ ] Unresolved local and owner capacity is retained.
- [ ] Same-connection and restart reconciliation never create a new
      `turn/start` for the original operation.
- [ ] Typed pre-admission rejection settles Agentd before local release.
- [ ] Terminal settlement is exact and idempotent across both owners.
- [ ] Unavailable history enters quarantine rather than inferred absence.

## D. Security and identity

- [ ] Worker and Agentd do not hold issuer or quarantine private keys.
- [ ] Final-use binding covers subject, destination, request, scope and payload.
- [ ] Signer, signature, validity interval, nonce, authority epoch and revocation
      frontier are checked.
- [ ] Revocation/frontier rollback fails closed.
- [ ] Issuer Unix socket and all protected ancestors have qualified ownership and
      permissions.
- [ ] Connected issuer is bound to expected UID, PID, process start time,
      executable digest, cgroup/service identity and host boot identity.
- [ ] Issuer process identity is sampled before and after the grant exchange.
- [ ] Trusted time and revocation distribution are independently qualified.
- [ ] Local frontier restore/relocation cannot silently roll back authority.
- [ ] Worker client exposes no model-visible, registered, MCP, connector,
      dynamic, extension or core tools.
- [ ] Logs/evidence contain no signing key, bearer credential or unrestricted
      prompt/output/context material.

## E. Target-host qualification

- [ ] Selected host boot, kernel, service units, namespaces, mount layout and
      process/socket identities are recorded.
- [ ] Exact accepted binaries and configuration are installed read-only.
- [ ] Durable journal and authority/quarantine stores pass integrity and
      anti-rollback recovery.
- [ ] Real provider audit exporter is independently authenticated.
- [ ] At least 30 and at most 200 canary operations complete, each with one
      unique provider audit record.
- [ ] p50, p95, p99, maximum latency and maximum RSS are recorded for the exact
      host/release.
- [ ] `provider-ack-loss` passes without replay.
- [ ] `event-lag` produces quarantine/non-success.
- [ ] `worker-kill-after-fence` cannot enable abort or a second send.
- [ ] `worker-restart` reopens the same operation without a new send.
- [ ] `agentd-restart` preserves dispatch digest/revision/capacity.
- [ ] `revocation-advance-before-entry` prevents physical send.
- [ ] `duplicate-owner` produces one fresh fence winner.
- [ ] `stale-revision` rejects without mutation or effect.
- [ ] Fault evidence binds source, operation, journal, provider audit and harness
      digests.
- [ ] Target-host manifest and provenance verification pass.

## F. Quarantine and resolution

- [ ] Every unresolved effect has an immutable evidence digest and retained
      capacity/ownership.
- [ ] Quarantine age and capacity alerts are operational.
- [ ] Resolution verifier binds operation, request, dispatch and evidence digests.
- [ ] Resolution signer, epoch, monotonic sequence, validity and nonce are
      checked against an independent durable frontier.
- [ ] `CloseSucceeded`, `CloseFailed`, `RemainQuarantined` and
      `AuthorizeReplacement` have distinct policies.
- [ ] A replacement uses a distinct operation id and provider idempotency key.
- [ ] No resolution authorizes replay of the original operation.
- [ ] Operator UI/API cannot mark success or permit retry without a verified
      resolution envelope.

## G. Canary, rollback and day-2 operations

- [ ] Admission limits, canary duration and stop conditions are explicit.
- [ ] Alerts exist for replay attempt, identity/frontier failure, owner/local
      divergence, terminal success without current owner and store corruption.
- [ ] Orphan-thread, unresolved-operation and quarantine metrics are collected.
- [ ] Rollback rehearsal preserves interpretation of every candidate record.
- [ ] Predecessor binary/schema compatibility is proved or a compatible snapshot
      plus anti-rollback frontier is available.
- [ ] Rollback does not delete journals, reset epochs/revisions, reuse old socket
      identity or relabel unknown effects.
- [ ] Quickstart, deployment, troubleshooting and operations documents were
      reviewed against the exact release.

## H. Independent decisions

- [ ] Security reviewer signs the issuer, key-custody, process identity, trusted
      time/revocation and anti-rollback evidence.
- [ ] Runtime reviewer signs the physical-send, reconciliation, terminal and
      capacity evidence.
- [ ] Operations reviewer signs target-host, canary, rollback and incident
      procedures.
- [ ] Independent acceptor signs the complete exact-candidate evidence set.
- [ ] Unresolved exceptions are enumerated with owner, expiry and explicit
      non-activation consequence.

## I. Activation and release

These are decisions, not automatic consequences of previous checkboxes:

- [ ] Activation authority explicitly approves the exact host/release.
- [ ] Promotion authority explicitly approves traffic widening.
- [ ] Release authority explicitly approves the final release.

Until all required evidence and decisions are current, the canonical claim
values remain:

```json
{
  "independentAcceptance": false,
  "activation": false,
  "promotion": false,
  "release": false
}
```

## Acceptance record

Record the decision in a separately signed object containing:

```text
candidate/source/tree/synthetic-merge identity
binary/config/host/issuer/provider identities
source and target-host evidence bundle digests
quarantine inventory digest
canary and rollback receipt digests
reviewer identities and decision timestamps
explicit claim values
```

Never edit an old acceptance record in place. Supersede it with a new monotonic,
source-bound record.
