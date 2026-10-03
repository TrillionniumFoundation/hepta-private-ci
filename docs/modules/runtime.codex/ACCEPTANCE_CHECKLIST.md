# runtime.codex acceptance checklist

This checklist is fail closed. Complete an item only with current evidence for
the exact candidate named in the acceptance record. `N/A` requires a written,
independently reviewed rationale and cannot erase a failed gate.

## A. Candidate identity

- [ ] Repository, exact source commit and source tree are recorded.
- [ ] Ordered synthetic-merge base/source parents and merge tree are recorded.
- [ ] Worktree cleanliness was checked before and after every source command.
- [ ] Binary, lockfile, toolchain, configuration and implementation-map digests
      are bound to the candidate.
- [ ] No mutable branch name is used as evidence identity.

## B. Repository source qualification

- [ ] Runtime binaries build with `--locked` from the exact candidate.
- [ ] Adapter terminal/correlation/deadline/recovery tests pass.
- [ ] Durable journal, abort, rejection, restart and no-replay tests pass.
- [ ] Agent protocol and lifecycle tests pass.
- [ ] Worker authority, issuer identity, cancellation, deadline, owner-loss,
      typestate and cleanup tests pass.
- [ ] The fence-aligned 22-cut crash-matrix record passes its declared floor,
      including 256-contender, restart, lost-ACK and stale/digest stress tests.
- [ ] The signed quarantine-protocol record passes its declared floor.
- [ ] Real repository Agentd/App Server product composition passes against the
      controlled provider and proves one physical request.
- [ ] Model-only tool topology passes.
- [ ] Strict Clippy passes with `-D warnings` for every declared package/target.
- [ ] Formatting passes without source mutation.
- [ ] Exact-head receipt status is `passed`.
- [ ] Ordered synthetic-merge receipt status is `passed`.
- [ ] Every command record/log is retained and digest-bound.
- [ ] Both GitHub attestation bundles verify for the retained receipt bytes.

A missing, skipped, cancelled, timed-out, zero-test, malformed, stale, dirty or
nonzero command keeps this section failed.

## C. Effect-entry and recovery invariants

- [ ] Owner/ingress, context, cancellation, deadline, revocation and
      `VerifiedUseToken::enter` checks occur before the server-owned fence.
- [ ] Agentd accepts exact effect-entry CAS only from `ContextAttached`.
- [ ] Only a fresh, exact, non-idempotent ACK grants one send permit.
- [ ] Idempotent, lost, mismatched or stale fence results grant no send.
- [ ] Post-fence abort is impossible at Agentd.
- [ ] Local abort proof is non-cloneable/non-serializable and destroyed once
      fence commit may be unknown.
- [ ] Unresolved local/owner capacity is retained.
- [ ] Same-connection/restart reconciliation creates no new `turn/start` for the
      original operation.
- [ ] Typed pre-admission rejection settles Agentd before local release.
- [ ] Terminal settlement is exact/idempotent across both owners and durable
      before thread cleanup.
- [ ] Unavailable history enters quarantine rather than inferred absence.

## D. Security and identity

- [ ] Worker/Agentd hold no issuer or quarantine private key.
- [ ] Final-use binding covers subject, destination, request, scope and payload.
- [ ] Signer, signature, validity, nonce, epoch and revocation frontier verify.
- [ ] Time/revocation/frontier rollback fails closed.
- [ ] Issuer socket and every protected ancestor have qualified ownership,
      permissions, mount and symlink behavior.
- [ ] Connected issuer is bound to expected UID, PID, process start time,
      executable digest, cgroup/service identity and host boot identity before
      and after the exchange.
- [ ] Trusted time and revocation distribution are independently qualified.
- [ ] Local frontier restore/relocation cannot silently roll back authority.
- [ ] Worker exposes no model-visible/registered MCP, connector, dynamic,
      extension or core tools.
- [ ] Logs/evidence contain no signing key, bearer credential or unrestricted
      prompt/output/context material.

## E. Target-host qualification

- [ ] Protected run consumed the same source SHA's passed/attested source-head
      and synthetic-merge receipts.
- [ ] Host boot, kernel, service units, namespaces, mounts and process/socket
      identities are recorded.
- [ ] Exact binaries/configuration are installed read-only.
- [ ] Journal and authority/quarantine stores pass integrity and anti-rollback
      recovery.
- [ ] Provider audit exporter and fault harness are independently authenticated.
- [ ] 30–200 canaries complete, each with one unique provider audit identity and
      unique terminal-correlation digest.
- [ ] p50/p95/p99/maximum latency and RSS are recorded.
- [ ] `provider-ack-loss` passes without replay.
- [ ] `event-lag` produces quarantine/non-success with capacity retained.
- [ ] `worker-kill-after-fence` enables neither abort nor a second send.
- [ ] `worker-restart` reopens the same operation without a new send.
- [ ] `agentd-restart` preserves digest, monotonic revision and capacity.
- [ ] `revocation-advance-before-entry` prevents the fence/send.
- [ ] `duplicate-owner` produces exactly one fresh winner and one send.
- [ ] `stale-revision` rejects without mutation or effect.
- [ ] Every fault binds source, operation, journal, provider and harness digests.
- [ ] Canonical target-host V3 manifest and provenance verification pass.

## F. Quarantine and resolution

- [ ] Every unresolved effect has immutable evidence and retained ownership.
- [ ] Quarantine age/capacity alerts are operational.
- [ ] Resolution verifier binds operation, request, dispatch and evidence set.
- [ ] Signer, epoch, monotonic sequence, validity and nonce verify against an
      independent durable frontier.
- [ ] `TerminalObserved` requires exact response and correlation evidence and an
      explicit succeeded/failed/interrupted outcome.
- [ ] `AbandonWithoutReplay` closes policy ownership without asserting provider
      absence or authorizing original-operation replay.
- [ ] No envelope means the effect remains quarantined; there is no ambient
      “remain quarantined” authority shortcut.
- [ ] `AuthorizeNewOperation` requires a distinct operation id, one attempt,
      provider idempotency key and any compensation prerequisite.
- [ ] Operator UI/API cannot mark success or permit replacement without a
      verified envelope.

## G. Canary, rollback and day-2 operations

- [ ] Admission limits, duration and stop conditions are explicit.
- [ ] Alerts exist for duplicate/replay, identity/frontier failure, owner/local
      divergence, owner revision rollback, success without current owner and
      store corruption.
- [ ] Orphan-thread, unresolved-operation and quarantine metrics are collected.
- [ ] Rollback rehearsal preserves interpretation of every record.
- [ ] Predecessor compatibility or a compatible snapshot plus anti-rollback
      frontier is available.
- [ ] Rollback does not delete journals, reset epochs/sequences, reuse process or
      socket identity, or relabel unknown effects.
- [ ] Quickstart, deployment, troubleshooting and operations documents match the
      exact release.

## H. Independent decisions

- [ ] Security reviewer signs issuer, custody, process identity, trusted
      time/revocation and anti-rollback evidence.
- [ ] Runtime reviewer signs physical-send, reconciliation, terminal and
      capacity evidence.
- [ ] Operations reviewer signs host, canary, rollback and incident procedures.
- [ ] Independent acceptor signs the complete exact-candidate evidence set.
- [ ] Exceptions list owner, expiry and explicit non-activation consequence.

## I. Activation and release

These are explicit decisions, not automatic consequences:

- [ ] Activation authority approves the exact host/release.
- [ ] Promotion authority approves traffic widening.
- [ ] Release authority approves the final release.

Until every required item and decision is current, canonical claims remain:

```json
{
  "independentAcceptance": false,
  "activation": false,
  "promotion": false,
  "release": false
}
```

## Acceptance record

The separately signed record contains:

```text
candidate/source/tree/synthetic-merge identity
binary/config/host/issuer/provider identities
source and target-host bundle digests
quarantine inventory digest
canary and rollback receipt digests
reviewer identities and decision timestamps
explicit claim values
```

Never edit an old record in place. Supersede it with a new monotonic,
source-bound record.
