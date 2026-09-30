# inference.worker recovery and operations runbook

This runbook is the concrete operating companion to `TECHNICAL.md`,
`CURRENT_STATUS.json`, the module execution dossier and the native-host guide.
It describes repository source behavior. It is not evidence that a real
provider, local accelerator, authority issuer, target host or deployment has
been independently qualified.

## 1. Public capability profiles

`inference.worker` exposes three deliberately different profiles:

| Profile | Repository status | Permitted claim |
| --- | --- | --- |
| `HostedAppServerWorker` | production candidate | Executes one exact-generation Agent/App Server turn through durable `inference.control`, final-use authority and no-replay recovery. Real-provider and target-host qualification remain external gates. |
| `LocalModelWorker` | experimental, non-production | Feature-gated framework for signed grants, verified manifests and inputs, trusted resource observation, aggregate resource accounting, durable dispatch and inspect-only recovery. It is not proof of a real weights/device driver. |
| `LegacyReceiptBoundary` | validation only | Validates request, lease, reservation and observation tuples and emits a deny-all receipt. It is not provider execution. |

No caller may use a fake `ModelDriver`, synthetic resource observer or unit-test
receipt as evidence that physical weights, tokenizer, runtime, device, memory
or isolation were consumed.

## 2. Hosted App Server state and replay policy

The durable owner records the exact source admission before external execution.
A fresh run progresses through `Reserved`, `Dispatching`, `Running` and a
terminal or indeterminate observation. The in-memory pre-effect abort proof is
non-cloneable and non-serializable. Only the live process holding that proof may
release a definitely-unsent dispatch.

After process loss, `Dispatching`, `Running`, `Cancelling` and `Indeterminate`
records are reconcile-only. Recovery may use the exact original App Server
thread history or a trusted terminal-receipt verifier. Recovery must never
create a second `turn/start`, infer that missing history means "not sent", or
convert unknown usage to zero.

The same-process turn-start reconciliation grace is selected through
`NativeRecoveryPolicy`. It is bounded to 10 milliseconds through 30 seconds;
the default remains two seconds. A longer window is not a retry grant.

## 3. Missing-history resolution

When exact App Server history is unavailable:

1. call `quarantine_missing_history` with a bounded operator reason;
2. keep the durable request identity, held-effect uncertainty and any monotonic
   usage already observed;
3. do not release or replay based only on elapsed time;
4. obtain a terminal receipt only through an implementation of
   `TrustedProviderTerminalReceiptVerifier` that authenticates the provider or
   an independently operated reconciler and binds the complete durable record;
5. call `reconcile_provider_terminal` with that verified receipt;
6. treat a reconciled provider success as terminal provider truth but
   `Quarantined`/`Unverified` unless owner authority was independently and
   atomically established for that terminal boundary.

A terminal receipt may leave token usage unknown. Unknown remains `None`. A
later usage refinement must be monotonic and bound to the same request, thread,
turn, model, provider and verifier witness.

## 4. Experimental local-model recovery

The local profile is enabled only by the `experimental-local-model` Cargo
feature. It requires:

- an Ed25519-verified `VerifiedResourceGrant` bound to issuer, authority epoch,
  nonce, worker subject/generation, complete model tuple, device identity and
  lease, aggregate memory, concurrency, token/usage ceilings, expiry and a
  monotonic revocation frontier;
- a `VerifiedModelManifest` and `VerifiedInput` whose semantic digests are
  recomputed at the boundary;
- a `TrustedClock` and a bounded `TrustedDeadline`;
- an injected asynchronous `LocalModelDriver` plus an independent
  `TrustedResourceObserver`;
- the existing `DurableInferenceControl` journal rather than a second local
  effect ledger.

Resource admission is aggregate. Model residency, request transient memory and
concurrency use checked arithmetic and RAII reservations. Failed physical
unload leaves the model in `Zombie`; device reset or unverifiable physical state
fences the generation and moves affected records to repair/quarantine rather
than deleting their handles.

Once durable effect entry has occurred, restart recovery calls `inspect` only.
It must not call `run` again. `MissingHistory`, `Pending` and `Ambiguous` remain
indeterminate and fence the generation until a qualified repair or terminal
observation is applied.

## 5. Required operational metrics

Export `NativeRecoverySnapshot` and `NativeRecoveryCounters` through the
selected host telemetry boundary. At minimum alert on:

- `indeterminate_count` and `oldest_indeterminate_age_ms`;
- `held_reservations` versus `native_maximum_in_flight`;
- reconcile attempts, successes, misses and failures;
- provider terminal-receipt verification successes and failures;
- `missing_usage_count` and `terminal_without_usage_count`;
- final-use authority denials;
- cancellation-to-interrupt sample count, total latency and maximum latency;
- journal bytes and record capacity;
- local generation fence reason, committed model bytes, transient request
  bytes, loaded models and active/quarantined requests.

New native observations persist their host observation time and the first
indeterminate time. `oldest_indeterminate_age_ms` therefore survives restart
for new records. Historical records may still require the operator-owned
compatibility projection; when neither source is available,
`age_evidence_complete` is false and age is `None`.

Experimental local observations also persist independently bounded
`usage_units`; an absent value remains unknown. Mid-run cancellation and
deadline expiry are owned by the worker rather than delegated to driver
cooperation: the in-flight future is dropped, the driver receives one bounded
interrupt/reconcile call, and any missing, pending, ambiguous, failed or timed
out interrupt retains request resources and fences the generation. A later
invocation may inspect the original operation but may never call `run` again.

## 6. History-retention contract

A selected App Server deployment must publish and qualify:

- whether ephemeral thread history survives worker, Agent and App Server
  restart;
- retention duration and deletion triggers;
- authenticated thread/read identity and provider correlation;
- behavior during provider failover, model-provider change and session drift;
- maximum reconciliation delay and event-channel loss behavior;
- how terminal usage is obtained when the terminal event omits usage;
- backup/restore and anti-rollback behavior.

If any required history is missing, source code cannot manufacture terminality.
The request stays quarantined until trusted evidence or an externally governed
resolution policy is applied.

## 7. Incident procedure

For a rising indeterminate or held-reservation count:

1. stop new admission before journal or slot exhaustion;
2. snapshot exact source head/tree, journal identity, Agent generation, App
   Server version/protocol/home/session/connection and authority frontier;
3. classify each record as pre-dispatch released, explicit pre-start rejection,
   exact-history recoverable, trusted-receipt recoverable, or unresolved;
4. reconcile only with the original durable identity;
5. retain unknown usage as unknown;
6. require independent review before any manual terminal override, capacity
   release, journal migration or history deletion;
7. canary the recovered generation and preserve rollback evidence.

For a local device reset or unload failure, fence the generation immediately,
stop new loads/runs, retain all handles and aggregate accounting, obtain trusted
zero-residency observations, and start a new generation only after the repair
receipt is reviewed.

## 8. Qualification boundary

Repository CI must bind source head, source tree, relevant blob identities,
Linux and macOS library tests, binaries, all targets, strict Clippy, clean tree
and the deterministic synthetic merge. These checks may establish repository
source qualification only.

They do not establish real weights/device consumption, OOM/device-reset/load-
kill behavior on target hardware, deployed issuer key custody, trusted time,
revocation distribution, real-provider terminal/usage truth, production
composition, independent acceptance, activation, promotion or release. Those
fields remain false or `not_established` in `CURRENT_STATUS.json` until an
external authority supplies exact-candidate evidence.
