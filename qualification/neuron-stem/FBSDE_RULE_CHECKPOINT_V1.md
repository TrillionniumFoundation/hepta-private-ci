# Durable research-rule checkpoints without reviving historical authority

Parent `fff3f7702fbf9629ed31cf9f5715f39670f62e40`, existing Draft PR #1550.
The original entry gains `durable_rule_checkpoint_v1`; old RuleSlot,
TransferTable, scientific profiles and native production owners remain unchanged.
This is an OPTIONAL persistence adapter for the same research state machine.
It does not connect SQLite records to the native artifact authorization surface.

## Persistence, ownership and uncertain outcomes

RuleCheckpoint uses one process-owned OS file lock and SQLite DELETE-journal
transactions with synchronous=FULL. A lifecycle event and its resulting bounded
state snapshot commit together. Storage is bounded by 512 rows, 64 KiB per event
or state encoding, and a 64 MiB SQLite page limit (rollback-journal space is extra).
Creation is explicit/create-only; reopen never initializes an absent database.
The directory must already be private and trusted. Symlink endpoints, another
writer, inherited process use, corrupt rows and inconsistent replay fail closed.
This is not a defence against a malicious filesystem owner replacing the root.

A current, independently retained owner anchor is REQUIRED to reopen: database
lineage, acknowledged sequence and digest. Recovery rejects a self-consistent old
backup that does not contain this anchor. A stale anchor supplied by a caller is
NOT proof of currentness; hashes are not signatures, consensus or authority.

Source work is preceded by durable intent. Recovery attempts are reserved before
calling the source, so a crash after reservation but before invocation may spend
one allowance without performing an experiment. A crash before commit cannot
enter the callback. Actual callback entries and charged reservations are separate
records; neither is reclassified as the other to improve costs.

Any storage uncertainty poisons the in-memory consumer. It cannot publish a result,
issue a new acknowledgement or retry a stale handle. A committed local `finish`
whose response is lost is NOT exactly-once delivery. Reconciliation preserves the
record but never automatically repeats an external effect. No external outbox or
receiver acknowledgement protocol is implemented in this step.

## Restart does not restore process-local authority

DurableRuleSlot reuses the original RuleSlot operations. No pending use handles,
locks, source closures or active table are serialized into reusable capabilities.
Every restart quarantines an active table. It preserves the lifetime recovery
attempt count; a retired or new generation cannot refill it. Incomplete recovery
keeps its same-epoch observations. A recovery receipt durably saved immediately
before the original RuleSlot applies it is replayed ONCE on restart. Invalid or
nonbijective evidence remains refused. All old events stay in the ledger.

Reopening an already reactivated table conservatively starts fresh recovery,
without replenishing the lifetime allowance. This can exhaust the allowance after
a later crash: safety is bought with explicit availability loss. Restoring an old
active snapshot to avoid that refusal would defeat the intended guarantee.

The existing 100ms process-CPU bound is unchanged. Normal begin/finish now check
an outer interval including persistence. Source callbacks, startup, restore/replay
and SQLite I/O remain separately measured/bounded by inventory, not asserted to
be a preemptive end-to-end realtime service. No clock, GC or thread policy changes.

## Real process experiment and interpretation

Seven event points (retire, verification intent, recovery request/receipt,
reactivation, finish, restart quarantine) are interrupted immediately before or
after SQL COMMIT. Two more cases exit inside actual source callbacks. All 16 use
new child processes and os._exit, leaving real database/rollback-journal bytes;
exit codes, process markers, independent owner floors and source entries survive.
The parent reopens the files rather than substituting mocked recovery results.

First complete execution: all 16 block direct use of the historical table; 15
recover within remaining allowance. In the reactivation-after-commit case, three
attempts were already spent; reopening retires that active table and the two
remaining calls cannot reidentify it. It remains quarantined with five charged
attempts. The failed availability outcome is retained, not retried to green.

All 33 finite source rules additionally undergo paid initial learning and restart
relearning. They produce 198 correct six-state applications, with 112 initial and
112 recovery source calls. Repeated executions are the SAME finite mechanism,
not new independent learning observations. No neural training, pretrained forward,
semantic gain, latency speedup or lifecycle cost superiority is claimed.

SQL bytes, external anchors, callback inventories, summaries and table effects
are checked separately from execution. The semantic event reducer is SHARED with
restart validation; the auditor is therefore not a fully independent lifecycle
implementation. Mutation tests, real exits, source-effect reference and raw files
provide complementary checks, not hardware execution attestation.

These are abrupt PROCESS exits, not storage-power-loss tests. SQLite atomicity
still depends on the VFS/filesystem/hardware honouring its synchronization contract:
https://www.sqlite.org/atomiccommit.html
https://www.sqlite.org/pragma.html#pragma_max_page_count
Connections are explicitly closed; transaction contexts alone do not close them:
https://docs.python.org/3.13/library/sqlite3.html

## Exact native owner mapping: read, NOT integrated

The following existing interfaces were inspected at the exact parent SHA:

- `codex-rs/hepta-learning-artifacts/src/owner_host.rs`:
  LearningArtifactOwnerHost::open_with_required_current_head uses an independently
  retained signed CURRENT floor. A research SQLite anchor must not be cast to it.
- `.../durable_snapshots.rs`: existing create-only, bounded withdrawal/lifecycle
  snapshots replay semantic records against independently supplied receipts.
- `.../pinned.rs`: RevalidatingCandidate::with_current requires an opaque
  VerifiedCurrentRegistryViewV1 issued by the native signed-head verifier. Its
  host owns synchronization with final effects; it is not a global lock itself.
- `.../owner_service.rs`: the existing named artifact writer owns publication and
  recovery checkpoints. Rule-environment drift is not automatically a dataset
  withdrawal; no new withdrawal or selector authority is invented here.
- `codex-rs/hepta-agentd/src/cognitive_ranker.rs`: the actual consumer removes its
  cache before obtaining CURRENT, restores it only on success, and requires an
  independent evaluated selection when loading a production candidate.

NONE of these Rust owners is modified or executed by this experiment. Connecting
the rule payload, signed-current provider, selector and final-use owner requires
its own native integration tests and restart evidence. The Python port does not
satisfy that pending gate or authorize production activation. Keep Draft.

Reproduce via the original entry, then mutate saved evidence:

    python fbsde_study.py --profile durable_rule_checkpoint_v1 --output /new/checkpoint
    python fbsde_checkpoint_artifact_checks.py -v /new/checkpoint
