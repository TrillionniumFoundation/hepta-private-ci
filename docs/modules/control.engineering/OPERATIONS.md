# control.engineering operations and recovery runbook

This runbook covers operation, recovery, evidence handling, and production-readiness
checks for `control.engineering`. It is an operational companion to
[TECHNICAL.md](TECHNICAL.md), [IMPLEMENTATION.md](IMPLEMENTATION.md), and
[INTEGRATION_HANDOFF.md](../../../tools/hepta-engineering-control/INTEGRATION_HANDOFF.md).
It does not grant merge, deployment, promotion, release, runtime, external-effect,
or independent-acceptance authority.

## 1. Production boundary

The source package may schedule bounded work, qualify candidates, persist
integration eligibility, and emit review/handoff records. Production composition
requires a separately authorized caller and externally governed identities.

The canonical repository fact `production_implementation` remains false until a
named product caller invokes the registered boundary and executable product tests
cover that path. Deployment readiness is stricter and additionally requires
independent review, authorized handoff, external key custody, strong-sandbox
evidence, an observed target deployment, and a rollback rehearsal.

Use
`control_engineering_v2.production.evaluate_production_readiness` to project
those already-authenticated facts. The projection is not an authenticator and
never creates authority. The CLI command `readiness-projection` is intentionally
non-authoritative, while the former `production-readiness` exit-gate spelling
fails closed. Do not treat caller-supplied booleans or digest-shaped strings as
proof of HSM/KMS custody, a distributed fence, an external audit anchor, review,
deployment or rollback. Those facts must first pass their typed signature
verifiers under the selected production trust store.

## 2. Preflight

Before starting or qualifying a deployment candidate:

1. Bind the exact repository, source commit, source tree, ordered parents, and
   canonical document/registry digests.
2. Require a clean tracked checkout and reject base drift.
3. Run the focused owner suite from the repository root:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v \
     -s tools/hepta-engineering-control -p 'test_*.py'
   ```

4. On the Linux qualification host, require the real Bubblewrap admission probe:

   ```sh
   HEPTA_REQUIRE_STRONG_SANDBOX=1 PYTHONDONTWRITEBYTECODE=1 \
     python3 -B -m unittest discover -v \
     -s tools/hepta-engineering-control -p 'test_*.py'
   ```

   A skipped or failed host-admission probe is not strong-sandbox evidence.
5. Keep candidate sandboxes credential-free. Do not mount the caller checkout,
   caller `.git`, host home directories, runtime sockets, or credential stores.
6. Store the SQLite owner database on a filesystem with the durability semantics
   required by the selected host. Use one connection per execution thread; writer
   transactions serialize through the implementation's `BEGIN IMMEDIATE`
   boundary.
7. Verify that the caller, reviewer, evidence signer, deployment operator, and key
   custodian satisfy the required identity separation before accepting their
   receipts.

## 3. Runtime health and observability

Monitor the selected host for at least these signals:

- audit-chain verification failures;
- SQLite open/integrity failures, busy/lock pressure, WAL growth, and disk-full
  conditions;
- assignment age, expired envelopes, lease expiry, stale revisions, path
  conflicts, cluster-global leader/revocation rollback, and holder-local
  fence-token/revision rollback;
- sandbox admission failures, timeouts, output-limit violations, and source or
  candidate drift;
- stale, malformed, replayed, or signature-invalid source/execution/evaluator
  evidence;
- sealed-decision verification failures and identity collisions;
- handoff, deployment, or rollback receipts that are absent, expired, or bound to
  a different target identity.

Do not invent universal alert thresholds in this document. Bind numeric latency,
capacity, WAL, disk, and retry thresholds to the selected target-host profile and
retain the raw measurements with the deployment evidence.

## 4. SQLite backup

A backup is recovery material, not an authority or acceptance receipt.

Before the first production composition and after schema or identity-boundary
changes, rehearse a recoverable backup:

1. Record the exact source commit/tree, schema version, database path, current
   assignment generation/frontier, relevant revocation frontier, and latest
   externally retained audit anchor.
2. Prefer SQLite's online backup mechanism from a trusted maintenance process. If
   the `sqlite3` CLI is the selected host tool, a bounded example is:

   ```sh
   sqlite3 "$ENGINEERING_DB" ".backup '$BACKUP_DB'"
   sqlite3 "$BACKUP_DB" "PRAGMA integrity_check; PRAGMA foreign_key_check;"
   ```

3. Hash the completed backup and store its manifest outside the database. The
   manifest must identify the source/tree, schema, backup digest, creation time,
   and the independent frontier/anchor values needed to detect stale restore.
4. Never treat an ad-hoc copy of the database plus `-wal`/`-shm` files as a
   verified backup. Use one documented, tested snapshot procedure.
5. Protect backup access separately from candidate execution and CI credentials.

## 5. Restore and recovery

Restore to a new path first; do not overwrite the only surviving copy.

1. Preserve the failed database, WAL/SHM files, command receipts, logs, and
   relevant Git/evidence identities for investigation.
2. Restore the selected backup to a new location.
3. Run SQLite integrity and foreign-key checks.
4. Open the restored database through `EngineeringStore`. Store construction
   must validate the schema and audit chain; a failure keeps the database
   quarantined.
5. Compare the restored assignment/revocation frontier and external audit anchor
   with independently retained values. The anchor must match both the audit-chain
   head and the deterministic durable owner-state snapshot digest; a restore that
   would resurrect revoked/superseded state or silently rewrite owner tables is
   rejected.
6. Run focused owner tests and the applicable exact-source qualification against
   the intended binary.
7. Only a separately authorized operator may switch a production caller to the
   recovered database. Keep the predecessor copy read-only until the recovery is
   independently accepted.

## 6. Schema and binary rollback

Rollback means selecting an explicitly compatible predecessor; it does not mean
restoring stale data.

- Verify predecessor compatibility with the current schema and durable records.
- Preserve revocations, lineage, fencing generations, both the cluster-global
  distributed leader/revocation frontier and every holder-local fence frontier,
  and immutable integration decisions across rollback.
- If a predecessor cannot interpret the current state without deleting or
  weakening evidence, do not start it.
- For additive migrations, rehearse crash-before-commit and crash-after-commit
  boundaries and confirm that the old binary cannot re-enter with a stale
  generation.
- Record the rollback predecessor and rehearsal receipt in the production
  readiness facts.

## 7. Evidence and key rotation

The in-process `HmacTrustStore` is a reference verifier, not production key
custody. Production signing keys remain outside this module under an independently
controlled keystore/HSM or equivalent custody boundary.

Critical production roles use distinct custodied keys. In particular,
`source_authority`, `ci_executor`, `independent_evaluator` and
`engineering_evidence_binder` may not be collapsed onto one HSM/KMS key even
when that key is hardware backed; hardware custody does not replace identity
separation. Each custody receipt binds the subject signing identity, cryptographic
algorithm, public-key digest and external attestation digest in addition to the
provider/key identifier. The custody authority signer must remain distinct from
the subject key it attests.

A key rotation must:

1. enroll a new signing identity through the external trust authority;
2. permit a bounded verification overlap when policy requires it;
3. issue fresh source/execution/review/handoff receipts using the new identity;
4. revoke the predecessor identity at the external authority;
5. verify that stale predecessor receipts fail the current freshness/revocation
   rules;
6. retain only public identifiers/digests required for audit in the engineering
   store.

Never copy a private production key into the candidate sandbox, SQLite owner
database, workflow logs, general evidence payloads, or repository.

## 8. Incident procedures

### Audit chain or database corruption

Stop writes, quarantine the database, preserve all state files and external
anchors, and attempt restore/reconciliation using Sections 4 and 5. Do not repair
hash-linked audit rows in place to make verification pass.

### Strong sandbox unavailable

Stop issuing `sandbox_tested` claims. Portable fixture results remain
`fixture_tested` and are ineligible for the production/deployment readiness
chain. Repair the host isolation capability or move qualification to an admitted
Linux host.

### Source or base drift

Invalidate the old envelope, candidate result, and dependent execution receipts.
Rebind the exact source/tree and regenerate scheduling/candidate evidence. Do not
reinterpret an old pass for a new Git object.

### Stale or invalid evidence

Withdraw eligibility, obtain fresh independently signed receipts, and recompute
the sealed binding. Never extend timestamps or rewrite an existing decision.

### Reviewer or signer identity collision

Treat the evidence set as ineligible. The generator cannot satisfy the independent
review identity, and shared signing identity also fails independence.

### Lost external acknowledgement

Treat the effect as indeterminate until the named terminal observer/reconciler
resolves the stable operation identity. Do not blindly redispatch an operation to
discover whether it committed.

### Deployment or rollback failure

Freeze further promotion, preserve the exact target and receipt identities, use
the separately authorized deployment controller to select the compatible
predecessor, and re-run the target-host verification before resuming.

## 9. Release evidence bundle

Before any external authority changes a production/deployment state, retain one
bundle that binds:

- exact repository/source/tree and document/registry digests;
- native symbol mapping and named production caller;
- executable product-test receipt;
- exact-source and synthetic-merge CI receipts;
- real strong-sandbox receipt;
- independent reviewer identity and acceptance receipt;
- authorized handoff receipt;
- external key-custody identity/receipt;
- deployment target identity and observed deployment receipt;
- backup digest and recovery/rollback rehearsal receipt;
- zero authority delta from `control.engineering`.

Missing, malformed, stale, or identity-mismatched evidence leaves the corresponding
readiness dimension open.

## Durable worker execution lifecycle

`orchestration_generations`, `worker_registrations`, `worker_claims`,
`worker_capacity_reservations`, heartbeat/result/completion observations and audit events
are owned by the same SQLite v10 writer. A claim is admissible only for the Worker
selected by the persisted plan, while its exact path lease is active and while the
persistent cross-generation reservation total remains within the registered capacity.
The final check, claim and reservation commit in one `BEGIN IMMEDIATE` transaction.
Result submission, timeout, revocation and recovery release the reservation exactly once;
replay never decrements capacity twice.

The named source-level product composition is `EngineeringControlProduct`. On every
process open, call `startup_reconcile` before admitting new claims: it expires stale
heartbeats, revalidates registration/lease/envelope frontiers, preserves indeterminate or
awaiting-completion facts and releases abandoned capacity without redispatching an effect.
`EngineeringControlProduct.claim()` enforces this ordering and fails closed with
`product_startup_reconciliation_required` until recovery succeeds in the current process
object; do not bypass it with a lower-layer claim helper in a product caller.
Current repository CI executes this owner separately for exact source and deterministic
base-merge identities. GitHub reviewer observations bind API reviewer IDs and commit SHAs
but explicitly carry no independent-acceptance or merge authority.


## Durable integration reconciliation

`integration_queue_generations` and `integration_queue_items` are owned by the same
SQLite v10 writer. A queue generation binds one persisted orchestration generation to the
exact integration base commit/tree. Candidate, reviewer and CI receipts additionally bind
the queue/orchestration/envelope semantic digests, source commit/tree and owner-context
digest. Reusing the same local IDs under another source, base, plan or owner therefore
fails before state mutation. These observations may reach only `ready_external_merge` and
confer no merge authority. A separately authenticated terminal observer may record
`terminal_merged` or `terminal_failed`; reopen must preserve the exact receipt and audit
anchor. Any pre-terminal base drift invalidates the generation and requires a new plan.

## Target-host qualification profile

Run the bounded profile on the same exact candidate and Linux strong-sandbox host used by
the product lane:

```sh
PYTHONPATH=tools/hepta-engineering-control \
  python3 -m control_engineering_v2.qualification_profile \
    --repository /path/to/exact/checkout \
    --iterations 7 --sandbox-mode strong \
    --output /retained/control-engineering-host-profile.json
```

Retain the JSON with the source/tree, runner identity and CI receipt. It reports store-open,
planning, queue-to-claim, atomic claim, heartbeat, expiry recovery, SQLite lock handoff,
WAL bytes, audit verification, online backup, restored-snapshot equality, controlled
`SQLITE_FULL` rollback and the unchanged complete sandbox cost. Compare measurements only
against the selected target-host profile; do not invent universal thresholds or delete
Git-object/materialized-workspace checks to make a benchmark green. The profile has every
authority field false and is not an operator acceptance receipt.


## Normal control-pipe service

Launch `python -m control_engineering_v2 serve --database OWNER_DB --repository REPO
--repository-full-name ORG/REPO --verifier-factory engineering_host:create_verifier`.
Configure the factory on an operator-controlled import path, never a candidate
workspace. There is no automatic reference signer. Monitor owner lock wait,
recovery scan delay, request rejection and bounded output-channel failure.

An unconsumed reply can follow a committed operation. Reopen the same database,
query `plan_state`/`claim_state`, and replay only the same native receipt identity.
Do not create another effect identity to discover whether a previous effect ran.
Scanning continues with idle/partial input; explicit host commands still control
retry/replanning and supply external completion/integration observations.
Historical stage state never grants current merge authorization.

Profile v2 records actual host/source identity, small-sample nearest-rank latency
and raw samples. Its queue and sandbox workload is sequential. SQLITE_FULL is a
page-limit injection into a disposable backup, not physical disk/power-loss proof.
Sustained concurrency, real external custody and deployment remain separate gates.
