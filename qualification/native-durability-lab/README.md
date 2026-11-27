# Native-agent durability fault lab

This is a **local mechanism comparison**, not an implementation of Temporal,
not a Hepta Runtime test, and not A/B/C or six-Cell-arm acceptance. It runs actual
Python worker processes, kills them with `SIGKILL`, and inspects two independent
SQLite stores. No model, credentials, network service, GPU, or Runtime checkout
is required. All effects are simulated rows in the local effect database.

## Research question and alternatives

Three architecture routes solve different problems:

1. **Durable orchestration / history replay.** Persist decisions and progress,
   replay compatible orchestration, and retry activities. This does not make an
   external activity idempotent. Temporal explicitly recommends idempotent
   activities. Our checkpoint controls isolate the lost-ack ambiguity; they do
   **not** implement or benchmark Temporal's history/replay machinery.
   [Temporal activity definition](https://docs.temporal.io/activity-definition)
   and [workflow definition](https://docs.temporal.io/workflow-definition).
2. **Transactional outbox plus consumer inbox.** Persist intent with local state;
   relay it repeatedly; atomically deduplicate at the effect service. AWS notes
   that an outbox can still deliver duplicates and therefore requires an
   idempotent consumer. Here the workflow and effect databases are separate, so
   no accidental cross-store transaction hides the failure window.
   [AWS transactional-outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).
3. **Effect-owned completion ledger and authority check.** Resolve a prior
   completion, or check current authority and mutate the protected resource in
   one transaction. The deduplication component follows the principle that the
   operation and durable completion record must be atomic, as in RIFL. Our
   authority-epoch extension is an experimental construction, not a claim that
   RIFL implements Hepta authorization.
   [RIFL, SOSP 2015](https://web.stanford.edu/~ouster/cgi-bin/papers/rifl.pdf).

The five executable arms are ablations of these boundaries:

| Arm | Recovery behavior | Effect dedupe | Authority boundary |
| --- | --- | --- | --- |
| `checkpoint_retry` | Retry incomplete work | None, deliberately unsafe | Planning snapshot |
| `checkpoint_hold` | Atomic dispatch claim; uncertain work stays UNKNOWN | No blind retry | Planning snapshot |
| `outbox_dedupe` | Replay durable outbox | Unique ID + payload digest in sink transaction | Planning snapshot |
| `outbox_preflight` | Replay durable outbox | Same sink ledger | Read current permission before call; deliberate TOCTOU control |
| `outbox_final_use` | Replay durable outbox | Same sink ledger | Current epoch/enabled flag and effect share a write transaction |

For an existing receipt, the final arm returns the old result without a new
effect even after revocation. This is no-new-effect reconciliation, not a new
grant; attempt-audit and workflow-checkpoint metadata are still written.
The preflight arm instead rejects that retry before retrieving its old receipt,
showing that recovery policy and new-effect authority are different decisions.

## Reproduce

Only the Python standard library is used. Run from this directory:

```sh
CPUS=$(python3 -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:2])))')
taskset -c "$CPUS" python3 -m unittest -v
taskset -c "$CPUS" python3 durability_lab.py run runs/my-new-run
```

The output directory must be new. Existing evidence is never overwritten.
`results.json` records source SHA-256, Python/SQLite versions, database settings,
each worker's exit code/events, attempted calls, durable effect count, receipt
count, task state and outbox count. Local runs retain SQLite files for inspection; those files are **not committed**.
There is no install step and no external effect.

## Observed candidate result

`RESULTS.json` summarizes the reviewed local run of **39 scenarios**:
30 process-kill cases (five arms × six crash locations), five controlled
revocation races, and four two-worker duplicate-delivery races. The accompanying
test suite has **13 test methods** with additional payload, epoch, expiry,
retention and competing-claim probes.

| Arm | Effect committed, worker killed before checkpoint | Revoke after preflight, before effect | Two simultaneous deliveries |
| --- | --- | --- | --- |
| checkpoint retry | **2 effects**, reports done | **1 stale effect** | **2 effects** |
| checkpoint hold | 1 effect, **HOLD_UNKNOWN** | **1 stale effect** | Separate claim test: competitor holds; 1 owner effect |
| outbox + dedupe | 1 effect, done | **1 stale effect** | 1 effect |
| outbox + preflight | 1 effect, done | **1 stale effect** | 1 effect |
| outbox + atomic final-use | 1 effect, done | **0 effects**, denied | 1 effect |

The unsafe controls must exhibit their failures; a green test suite means those
predictions were observed, **not** that every arm is safe.

Crash points are before intent commit, after intent commit, before dispatch,
inside the uncommitted effect transaction, after effect commit, and after local
checkpoint. `SIGKILL` is verified as return code `-9`. Before-intent and
inside-effect crashes must roll back their uncommitted changes. Barrier files
control the authorization race: the controller waits until preflight completed,
commits revocation, and only then releases the worker. Sleeps only poll the
barrier; they do not determine the race's correctness.

## Falsifiable claims and limits

- For a stable ID and retained sink ledger, every tested outbox crash/retry must
  leave exactly one effect. Any extra effect falsifies the dedupe claim.
- If epoch revocation commits before a new final-use sink transaction, it must
  leave zero new effects. An effect falsifies the atomic-authority claim.
- A separate preflight is insufficient: the barrier race must reproduce one
  stale effect in that control. If it does not, the race fixture is suspect.
- The hold arm's atomic claim allows only one dispatcher, but intentionally
  sacrifices progress after ambiguous crashes. Before-effect crashes can leave
  zero effects and permanent UNKNOWN. There is no reconciliation service or
  lease-based takeover in this experiment.
- The sink binds the **exact payload bytes**, not semantic equivalence. A new ID
  for the same real-world operation is not deduplicated. No authenticated
  capability issuer, canonical tool schema, authorization budget or separate
  worker-generation protocol is implemented.
  Authority is a trusted local singleton and the epoch/deadline are supplied by
  the local plan; this is not a signed or target-bound capability proof.
- **Retention is part of the guarantee.** A negative test deletes the sink
  dedupe record after an unacknowledged commit, then demonstrates two effects on
  late retry. Real providers have bounded contracts too: Stripe API v1 permits
  pruning keys after at least 24 hours, after which reuse can be a new request.
  [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests).
- Epoch revocation and the simulated effect serialize in one SQLite write
  transaction. This is not atomic authorization across an unrelated HTTP tool.
  A legacy external API must supply an equivalent conditional/idempotent
  primitive or remain uncertain; the lab cannot manufacture that guarantee.
- Expiration is checked at the authorization-read linearization point. It is
  **not a guarantee that wall-clock expiry has not passed by physical COMMIT**.
  An independent review probe pauses after the check and demonstrates this
  distinction. The local wall clock is trusted and clock rollback is untested.
- SQLite permits one writer at a time. `BEGIN IMMEDIATE`, busy timeout and
  `synchronous=FULL` are explicit; observed on-disk journal settings are in the
  report. There is no distributed consensus, power-loss, disk-corruption or
  filesystem durability test. Process-kill recovery must not be generalized to
  hardware failures.
  [SQLite transactions](https://www.sqlite.org/lang_transaction.html) and
  [atomic-commit assumptions](https://www.sqlite.org/atomiccommit.html).
- Mixed-route restart, network partitions, adversarial ledger mutation and
  production policy/version migration are not modeled. The explicit retention
  deletion test is an unsafe ablation, not a supported cleanup procedure.

## Next discriminating experiments

Keep authority semantics explicit: an admission-time Prepare may intentionally
remain executable after later revocation, unlike strict sink-time epoch checks.
Test the chosen contract rather than treating both as the same guarantee.

Useful next directions are deterministic history replay under code/schema
change, budget/slot-bound retries with new operation IDs, current-generation
fencing versus max-seen-only fencing, bounded receipt retention with stale-ID
rejection, and an actual Runtime/tool-adapter fault campaign once its source,
toolchain and physical input requirements are available. None is claimed closed
by this local lab. `runtime_qualification=false` and
`physical_execution_proven=false` remain unconditional.

## Publication and CI boundary

The committed result is a concise local observation, not hosted-CI evidence.
The separate read-only workflow rechecks the exact PR source and prospective
merge, runs the tests and prints a fresh matrix. No SQLite files are uploaded.
Actual Hepta Runtime integration, signed FinalUse, real providers/models and
target-device acceptance remain unqualified by this lab.
