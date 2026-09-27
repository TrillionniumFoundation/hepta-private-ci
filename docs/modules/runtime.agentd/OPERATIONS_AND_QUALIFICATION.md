# runtime.agentd operations and qualification

This document defines the executable evidence and operating boundary for
`runtime.agentd`. It complements `TECHNICAL.md`; it does not replace the module's
architecture, contract, data-authority or implementation map.

No live branch, pull request, workflow conclusion, source SHA, merge SHA, host
measurement, acceptance decision or release digest is committed here. Those
facts are generated from the exact candidate and retained as external CI or
operator evidence. Repository prose never activates Agentd.

## 1. Candidate identity and required fan-in

A relevant lifecycle or inference change must pass two independently executed
candidate lanes before `CI required` can succeed:

1. **source-head** checks out the exact pull-request source SHA;
2. **base-merge** checks out GitHub's merge candidate and verifies its tree is
   exactly `git merge-tree --write-tree BASE SOURCE`.

Both lanes run Linux and macOS instances of owner libraries, native libraries,
native process tests, daemon process tests, product process tests, strict Clippy
and the read-only profile. Missing, skipped, stale, failed, duplicate or tampered
receipts fail the aggregate. A path-scoped job is not allowed to turn an
applicable Agentd gate into an accepted skip.

`scripts/hepta_runtime_agentd_closure.py` produces the candidate-local current
implementation map. It binds the exact source commit, tree, every verified source
blob, the static implementation-map blob and the source invariants. The generated
JSON is uploaded as CI evidence and is never copied back into the repository as a
cached "current" status.

Engineering receipts establish candidate behavior only. They are not production
signatures, operator acceptance, deployment authority, promotion or release.

## 2. Canonical product-composition invariant

A canonical Agentd product profile is valid only when one typed bootstrap binds:

- the canonical intelligence runner;
- the authoritative owner-input provider;
- the current durable Neuron owner and frontier;
- the runtime.codex executor;
- the host-owned physical input provider;
- the pinned final-use authority configuration;
- bounded queue, concurrency and recovery limits.

Partial installation is rejected. The runtime.codex supervisor is a required
`RuntimeTasks` owner. Canonical capability and admission remain closed until
startup reconciliation has completed and no dispatch-fenced unknown operation
blocks readiness.

Queue capacity is reserved before asynchronous canonical preparation mutates the
run coordinator. A scheduling failure is rolled back through the in-process typed
state transition, not through Agentd's own UDS. Different run identities may
execute concurrently, while exact duplicate/recovery work shares a keyed lock.
Drain, cancellation and generation fencing cancel every active worker and preserve
unknown external effects as `Indeterminate`.

Terminal operations leave the active recovery scan only after publication of an
independently synced terminal witness. Archive loss, witness drift, simultaneous
active/archive identity, semantic drift or journal corruption fails closed and
cannot turn a historical run into fresh dispatch authority.

## 3. Target-host evidence boundary

The authoritative scenario and receipt schema is
`QUALIFICATION_CONTRACT.json`. Destructive scenarios must run only on a disposable
host or disposable filesystem bearing the target-host marker required by the
qualification harness. Never fill, remount, corrupt, kill or permission-change a
production volume or production Agentd.

Every target-host receipt binds:

- exact source commit and tree;
- exact tested artifact digests;
- host and kernel/platform identity;
- effective configuration digest;
- scenario and operation identities;
- initial and final state digests;
- command, exit status and immutable log digest;
- every required observable invariant;
- explicit `production_activation: false`.

Required scenarios include drain under load, bounded backpressure, Agentd and
worker crash cuts, ENOSPC/read-only/fsync/rename faults, journal corruption,
stale generation, authority revocation, fixed-workload capacity/latency and
faulted soak/recovery. Unit tests, source inspection and Python fixture tests do
not substitute for these physical receipts.

## 4. Observability and SLO admission

Before operator acceptance, the deployed candidate must export the metric set in
`QUALIFICATION_CONTRACT.json`. Labels must be bounded; prompt text, model output,
credentials, authority tokens and private memory must never appear in metrics or
logs.

The initial operating objectives are admission criteria, not repository claims:

- zero duplicate physical dispatch for one durable operation identity;
- zero stale-generation mutation;
- zero acknowledged-but-nondurable admission or terminal publication;
- zero fabricated success or negative outcome after an unknown effect;
- bounded control connections, queue, active jobs and retained identities;
- no monotonic descriptor, task, process, journal or memory growth in soak;
- complete accounting of terminal, indeterminate, quarantined and archived runs.

Latency percentiles, drain deadlines, maximum acceptable indeterminate age and
resource ceilings must be selected from target-host measurements. A unit-test
wall-clock value is not an SLO.

## 5. Incident and recovery rules

On any durability, authority, fencing or terminal-correlation failure:

1. close new admission through the installed owner lifecycle;
2. preserve the exact candidate, artifact digests, configuration, logs and state;
3. cancel active workers without claiming their external effects stopped;
4. reconcile the original operation IDs; never mint replacements to erase an
   unknown result;
5. quarantine corrupt or semantically conflicting identities;
6. keep terminal witnesses and archives until the approved retention procedure
   proves deletion cannot resurrect dispatch authority.

A connection timeout, process exit or interrupt acknowledgement is not terminal
model or external-effect evidence. Recovery may report applied, not applied,
terminal failure, cancellation, quarantine or indeterminate only when the named
owner supplies the corresponding observation.

## 6. Rollback

Rollback is a new fenced owner generation, not a rewind of state, key epochs or
operation identities.

Before rollback:

- close admission and drain/reconcile as far as the deadline permits;
- retain a digest-bound state snapshot and unresolved-operation inventory;
- prove the predecessor binary can read every current schema and journal record;
- preserve terminal witnesses and unknown-effect responsibility;
- verify the predecessor will not redispatch a record introduced by the newer
  binary.

If schema or journal compatibility is unknown, stop in recovery review. Do not
start an older binary automatically.

## 7. Release-candidate provenance

A release-candidate workflow must build from an exact approved commit, retain the
actual tested Agentd and worker bytes, produce a manifest containing source/tree,
compiler, lockfile, workflow, configuration and binary digests, and issue GitHub
build-provenance attestations for that manifest and artifact bundle. Digest-only
engineering receipts are not release artifacts.

The provenance workflow creates no release, deployment or activation. Independent
security review, operator acceptance, promotion and release decisions must refer
to the exact attested artifact digest and remain distinct from the implementer and
workflow generator.

## 8. Activation stop conditions

Activation is prohibited while any of the following is absent or failed:

- successful exact source-head and base-merge gates;
- required target-host scenario receipts;
- repeated green default-branch candidates;
- approved SLOs and alert delivery;
- rehearsed rollback;
- independent security acceptance;
- exact release-artifact provenance;
- explicit operator activation decision.

A successful repository merge only integrates source. It never satisfies these
external gates by itself.
