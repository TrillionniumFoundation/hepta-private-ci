# inference.control operator runbook

This runbook applies to the exact-plan native App Server profile implemented by
`codex-hepta-infer-core` and `codex-hepta-infer-worker-host`. It is an operating
procedure, not an activation or release authorization. The generated source
status remains authoritative for qualification claims:
`TECHNICAL_STATUS.generated.md`.

## 1. Non-negotiable safety rules

1. Never edit the active journal, a checkpoint, or an archive segment by hand.
2. Never copy a journal while a writer owns it and then use the copy as an
   active generation.
3. Never replay a recovered `Dispatching`, `Running`, `Cancelling`, or
   `Indeterminate` request merely because the worker restarted.
4. Cancellation intent is not terminal evidence and never frees capacity.
5. There is no force-release command. An indeterminate slot is released only by
   a verified terminal/usage receipt or by revision-bound, two-person
   retirement.
6. Never place a long-lived model-output encryption key in the worker process,
   CLI arguments, journal, or execution bundle. The worker may talk only to the
   UID-bound output-vault socket.
7. Never infer successful completion from provider queue admission, JSON-RPC
   request acceptance, an interrupt acknowledgement, or a health check.
8. Never treat repository CI, this runbook, or a module owner as independent
   acceptance, activation, promotion, or release authority.

## 2. Production inputs

The native worker requires all of the following before it can cross the external
effect boundary:

- an absolute owner-only durable-journal path;
- an owner-only execution trust store;
- a signed execution-authority bundle containing independent manifest, quota,
  resource, and data-policy signatures;
- a final-use authority configuration for the independently operated local
  grant service;
- an exact Agent, worker generation, provider/model, tokenizer, template,
  runtime ABI, adapter ABI, payload, quota, resource, and output-policy binding;
- for `external_encrypted`, an owner-only Unix output-vault configuration whose
  socket peer UID and filesystem permissions are verified by the worker.

The production CLI rejects a bundle that does not match the command-line request
ID, Agent principal, model ID, or worker generation.

## 3. State semantics

| State | Meaning | Capacity | Permitted next evidence |
| --- | --- | --- | --- |
| `Reserved` | Admission is durable; no provider effect is known to have started. | Held | exact-plan dispatch, or a proven pre-dispatch stop |
| `Dispatching` | Write-ahead dispatch is durable; the effect may have started. | Held | start identity, signed terminal evidence, or indeterminate observation |
| `Running` | Exact provider thread and turn are durable. | Held | terminal observation or signed reconciliation |
| `Cancelling` | Cancellation intent is durable; terminality is unknown. | Held | terminal observation or signed reconciliation |
| `Indeterminate` | The effect may have happened but no trusted terminal state exists. | Held | fresh signed reconciliation or two-person retirement |
| `Released` | Trusted terminality, safe pre-effect abort, explicit safe rejection, or audited retirement. | Released | immutable except checkpoint/archive maintenance |

A process restart can recreate none of the in-memory pre-effect abort proof. A
recovered `Dispatching` record therefore remains reconcile-only.

## 4. Observe the owner

Run:

```bash
hepta-infer-maintenance status \
  --journal /absolute/path/to/inference-control.journal
```

The command acquires the same exclusive owner lock as the worker. Run it only
when the worker is intentionally stopped or through the service manager's
maintenance window. It emits:

- active journal bytes;
- checkpoint generation;
- counts for `Reserved`, `Dispatching`, `Running`, `Cancelling`,
  `Indeterminate`, and `Released`;
- protected-output count;
- expired encrypted-reference count.

### Alert thresholds

- **P1:** any `Indeterminate` record remains unresolved for 30 minutes, measured
  from the durable command/evidence timeline retained by the service manager.
- **P1:** `indeterminate >= maximum_in_flight`; no new execution can be admitted.
- **P1:** journal bytes exceed 85% of 64 MiB after a successful maintenance
  generation.
- **P2:** journal bytes exceed 70% of 64 MiB.
- **P2:** one or more expired encrypted references remain undeleted for one
  hour.
- **P2:** two consecutive checkpoint generations fail.
- **P2:** final-use, trust-store, or output-vault authentication failures exceed
  five in ten minutes for one owner.
- **Security incident:** raw model output is observed in an active journal,
  checkpoint, command record, or log. Stop the owner, preserve evidence, rotate
  affected data keys, and invoke the incident process.

The machine-readable form is `SLO_ALERTS.json`.

## 5. Crash-safe checkpoint and archive maintenance

Run during an exclusive maintenance window:

```bash
hepta-infer-maintenance compact \
  --journal /absolute/path/to/inference-control.journal \
  > /protected/evidence/compact-receipt.json
```

The command:

1. reads the exact active generation;
2. writes a content-addressed predecessor archive segment;
3. fsyncs the archive directory;
4. writes a content-addressed checkpoint containing the complete live state;
5. fsyncs the checkpoint directory;
6. writes and fsyncs a replacement active generation containing the checkpoint
   reference;
7. atomically renames the replacement and fsyncs the parent directory;
8. keeps the replacement file descriptor as the only locked writer.

The receipt identifies the generation, archive segment digest, archive-chain
digest, checkpoint digest, active bytes, record count, and expired encrypted
references. Retain it with the exact source/tested SHA evidence.

If the command fails before rename, reopening must recover the predecessor
journal. If it fails after rename, reopening must recover one complete new
checkpoint generation. Never guess which generation won; reopen through
`DurableInferenceControl`, which verifies the digest, filename, schema,
permissions, generation, capacity, and every record invariant.

### Expired encrypted output references

The compact receipt is the deletion work queue. Submit each returned reference
to the independently operated output vault, retain the vault deletion evidence,
and retry until every reference is confirmed deleted. Do not discard the
compact receipt merely because the active checkpoint no longer contains the
reference; the content-addressed predecessor archive and maintenance receipt are
part of the audit trail and follow their separately governed retention policy.

## 6. Reconcile an indeterminate execution

Obtain all four historical execution-authority signatures and a **fresh**
reconciliation receipt from an authorized reconciliation issuer. The receipt
must bind:

- historical execution authority epoch;
- current reconciliation-issuer authority epoch;
- request and principal;
- execution-binding and dispatch digests;
- provider thread and turn;
- provider and model digest;
- monotonic terminal sequence;
- terminal status, usage, and output digest/reference;
- a short current validity window.

Then run:

```bash
hepta-infer-recovery reconcile \
  --journal /absolute/path/to/inference-control.journal \
  --trust-store /protected/current-trust-store.json \
  --execution-authority-bundle /protected/original-execution-bundle.json \
  --evidence /protected/fresh-reconciliation-receipt.json
```

The verifier permits the original dispatch lease to be expired, because it
cannot authorize another effect. It re-verifies the historical four-authority
bundle for identity and verifies the fresh receipt against the current rotated
issuer key window. A stale, revoked, mismatched, non-monotonic, unsigned, or
wrong-dispatch receipt is rejected.

## 7. Retire an unrecoverable execution

Retirement is exceptional. First document why no independent provider terminal
record can be obtained. Two distinct authorized operators must sign the exact
request, principal, execution binding, dispatch digest, and **current record
revision**, with a fresh short validity window.

Run:

```bash
hepta-infer-recovery retire \
  --journal /absolute/path/to/inference-control.journal \
  --trust-store /protected/current-trust-store.json \
  --execution-authority-bundle /protected/original-execution-bundle.json \
  --evidence /protected/two-person-retirement.json
```

The tool rejects one-person approval, repeated key IDs, repeated signer IDs,
expired/revoked keys, stale record revisions, and any execution or dispatch
mismatch. The durable record retains both operator and key identities, the
reason code, reason, and retirement digest.

## 8. Key rotation and revocation

1. Publish the new key with a future `not_before_authority_epoch` and retain the
   old key through the final epoch in which old evidence may legitimately have
   been issued.
2. Move issuers/operators to the new epoch.
3. Verify a non-production signed vector for every role.
4. Revoke the old key at an explicit authority epoch. A key is invalid at and
   after its `revoked_at_authority_epoch`.
5. Distribute the owner-only trust store atomically. Do not partially edit it in
   place.
6. Retain the old signed execution bundles; post-effect recovery re-verifies the
   historical execution epoch while accepting a fresh reconciliation or
   retirement signature from a later, non-revoked key epoch.

## 9. Output-vault outage

- Before effect: an `external_encrypted` policy without a configured protector
  is rejected and the reservation is safely stopped before dispatch.
- After effect: if output protection fails, the worker writes no plaintext,
  records an output-free quarantined indeterminate observation, retains the
  slot, and returns an error. Recover only with signed terminal evidence or the
  dual-control retirement procedure.
- Never downgrade a confidential/restricted policy to digest-only in the
  worker. Issue a new independently signed execution bundle instead.

## 10. Corruption or permission failure

A malformed line, incomplete non-newline tail, checkpoint digest mismatch,
unsafe checkpoint permission, content-address collision, or writer I/O failure
fails closed. The writer is poisoned after an uncertain write/maintenance
failure.

1. Stop the service without deleting any file.
2. Capture filesystem metadata and immutable copies of the active journal,
   checkpoint directory, archive directory, and service logs.
3. Verify the last exact source/tested SHA and CI evidence receipt.
4. Reopen only in an isolated recovery environment using the normal verifier.
5. Escalate to security and storage owners. Do not truncate, append, chmod, or
   rename files to force startup.

## 11. Qualification evidence

A candidate is repository-qualified only when the final exact source head has:

- green `source-head` and deterministic prospective `base-merge` lanes;
- green `native-host` lane;
- current-state and implementation-map checks;
- formatting, locked metadata, tests, strict Clippy, crash/fault/tamper matrix,
  and multi-generation soak;
- command records and a `hepta.inference-control-evidence.v1` receipt binding
  source SHA, tested SHA, base SHA, candidate tree, check URL, and record hashes.

Those facts still do not grant independent acceptance, target-host activation,
promotion, or release.

## 12. Admitted-response uncertainty and writer capacity

Use [WRITER_BOUNDARIES.md](WRITER_BOUNDARIES.md) when tuning the current owner.
An `AcceptedDeadlineExceeded` or `AcceptedReplyLost` result requires observing
that exact request; it is not a safe retry or cancellation receipt. The writer
may still commit. Preserve the journal and its lifecycle lock, and use existing
signed terminal reconciliation for a potentially dispatched effect.

For scrape-heavy callers, request a serialized `metrics` refresh at a bounded
cadence and read `published_metrics` between refreshes. Preserve observation age
and do not treat stale counts as admission/authorization. Keep real-provider,
storage-fault and target-host qualification separate from pilot FIFO timings.
