# learning.plasticity runtime resource and recovery contract

This document specifies the current Agentd product-runtime contract for governed
parameter and topology proposal admission. It supplements `TECHNICAL.md`,
`CURRENT_IMPLEMENTATION.md`, `OPERATIONS.md`, and `DEVELOPER_QUICKSTART.md`.
It does not grant selection, installation, topology-application, promotion, or
release authority.

## 1. Preserved authority boundary

`PlasticityRuntimeHandleV1` is a bounded producer handle. It contains no proposal
registry writer, anchor store, owner-evidence resolver, or learning-evidence trust
root. Those mutable and privileged resources remain in the single long-lived
`PlasticityRuntimeOwnerV1` attached to one Agentd generation.

Parameter and topology requests therefore share one physical owner even though
they have separate bounded queues. Creating, cloning, timing out, or dropping a
handle cannot create another writer or transfer the owner's authority.

Static validation never replaces final-use validation. Every accepted request
still reaches the existing host/product chain, which recomputes current artifact
and learning-ledger frontiers, resolves exact owner evidence, rechecks trusted
signatures and role separation, and commits through the existing append-only
registry plus external anchor path.

## 2. Aggregate resource admission

Queue length is not treated as a memory bound. Before either queue accepts a
request, Agentd computes two charges:

- a conservative retained-footprint charge covering the typed request, vector
  capacities, bounded identifier storage, queue/oneshot overhead, and scratch or
  clone headroom;
- a work charge covering generator signal/scale evaluation, generated deltas,
  mutation-policy rules, candidate evaluation material, topology changes, and
  writer handoffs.

The per-request ceilings remain:

```text
retained-footprint charge <= 2 MiB
estimated work units       <= 16,384
```

Both parameter and topology queues draw from one aggregate ledger:

```text
aggregate retained-footprint charge <= 8 MiB
aggregate work units                <= 65,536
```

Admission is fail-fast. If either aggregate dimension is exhausted, the request
returns `PlasticityRuntimeCallErrorV1::Overloaded` before entering a queue. No
second writer, unbounded wait list, or hidden overflow queue is created.

A reservation is owned by the queued/in-flight command, not by the caller's
response future. Consequently:

- cancellation or timeout before queue insertion releases the reservation;
- cancellation while queued causes the owner to discard the command and then
  release the reservation;
- cancellation or response loss after durable work starts does not release the
  reservation until the owner reaches the real terminal point;
- a caller cannot free capacity early merely by abandoning its response.

Arithmetic is checked. Unknown overflow, zero budgets, underdeclared budgets,
and per-request ceiling violations fail closed.

## 3. Fairness, shutdown, and request isolation

Parameter and topology retain separate bounded queues and alternating preference.
The owner checks generation shutdown before every fast-path dequeue, so continuous
producer traffic cannot indefinitely hide the shutdown signal.

On shutdown the owner closes both receivers and rejects queued-but-not-started
commands. A command already in synchronous product execution is allowed to reach
its durable terminal or failure boundary; shutdown does not pretend that an
append was undone.

Cancellation, deadline expiry, and budget rejection are request outcomes. They
are sent to the affected request and do not terminate the shared owner. Owner
termination is reserved for loss of the unique engine or a failed blocking worker
that makes safe continuation impossible.

The current Running/ready Agentd generation is checked before taking the engine
and again at the blocking-worker final-use boundary. This narrows the queue-to-use
race without converting a post-append cancellation into rollback.

## 4. Static validation reuse

The runtime maintains a bounded 64-entry least-recently-used hint cache for exact
static request identities.

For parameter requests the cache key binds the complete generator profile,
mutation policy, signal values, generated candidate set, deltas, and generator
digest. For topology requests it binds the complete generation context, ordered
changes, and full writer-handoff plans.

A cache hit may skip deterministic regeneration or topology-generation shape
validation at runtime admission. It never caches:

- artifact or learning-ledger frontier validity;
- owner-evidence resolution;
- revocation state or trust epoch;
- signature validity or role independence;
- Agentd generation readiness;
- final-use authorization;
- registry predecessor or external-anchor success.

The product adapter intentionally repeats defense-in-depth validation. Cache
poisoning or eviction can at worst remove the optimization; it cannot create a
proposal fact or an authorization decision.

## 5. Timing and overload evidence

`PlasticityRuntimeTimingV1` records:

```text
static_validation_micros
quota_admission_micros
queue_wait_micros
blocking_execution_micros
total_micros
encoded_bytes
estimated_work_units
static_validation_cache_hit
```

`blocking_execution_micros` covers final frontier/evidence resolution, trusted
signature checks, registry append, external anchor commit, and synchronous fsync
work. Store-specific receipts remain the authoritative evidence for append and
anchor success; runtime timing is operational telemetry, not a replacement for
those receipts.

Operators should alert on sustained overload, queue-wait growth, or blocking
execution growth. The owner must not add a second writer merely to hide a slow
fsync or evidence source. Read-only/static work may occur before queue insertion;
final use and durable mutation remain serialized by the unique owner.

## 6. Recovery and uncertain outcomes

A caller timeout or lost response after submission is an uncertain outcome, not
proof that no write occurred. Recovery uses the exact proposal identity,
predecessor, registry frame, committed anchor, and control-engineering terminal
receipt where applicable.

The same fixed candidate is qualified against the following matrix:

1. first parameter append and external anchor commit;
2. first topology append and external anchor commit;
3. daemon shutdown and process reconstruction;
4. acknowledged registry/anchor reopen;
5. exact idempotent replay returning the original sequence and anchor;
6. registry-only rollback rejection against independently retained anchor state;
7. incomplete crash-tail repair only after all complete predecessors validate;
8. complete invalid frame preservation and fail-closed recovery;
9. registry/anchor hard-link alias rejection;
10. equal mount/snapshot rollback-domain rejection.

Repository qualification runs source-head and deterministic synthetic-merge lanes
without editing the candidate. Target-host acceptance must additionally retain
inode/device identity, independently derived mount and snapshot-domain evidence,
file and parent-directory fsync observations, forced recovery exercises, and
independent semantic/security acceptance.

## 7. Verification commands

From the repository root:

```bash
python3 scripts/test_learning_plasticity_grammar_contract.py
python3 scripts/hepta-docs.py verify
python3 scripts/hepta-module-docs.py refresh-derived --check
python3 scripts/hepta-implementation-maps.py verify
```

From `codex-rs/`:

```bash
cargo fmt --manifest-path Cargo.toml \
  --package codex-hepta-plasticity \
  --package codex-hepta-learning-artifacts \
  --package codex-hepta-intelligence \
  --package codex-hepta-agentd -- --check

cargo check --locked --all-targets \
  -p codex-hepta-plasticity \
  -p codex-hepta-learning-artifacts \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd

just test --locked -p codex-hepta-agentd --lib plasticity_ --test-threads=1
just test --locked -p codex-hepta-agentd \
  --test plasticity_process_e2e --test-threads=1

cargo clippy --locked --all-targets \
  -p codex-hepta-plasticity \
  -p codex-hepta-learning-artifacts \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd -- -D warnings
```

A queued, skipped, self-modified, or different-SHA run is not a passing receipt.
Production execution, independent acceptance, activation, and release remain
false until their distinct external receipts exist.
