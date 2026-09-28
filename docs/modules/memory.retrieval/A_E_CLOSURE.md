# memory.retrieval A–E closure

Status: source convergence candidate. Production activation and release remain false.

This document is the acceptance ledger for the 2026-09-28 convergence branch. It separates source implementation, native verification, target-host measurement, and independent acceptance. A green source build is not a production rollout decision.

## A — Correctness and causal facts

The candidate uses four conservative evidence stages:

1. `AssignmentPrepared`: final SQLite, ranker, signed-lifecycle and request-deadline fences passed and the idempotent learning assignment is durable. This stage claims no external effect.
2. `Published`: the App Server returned a typed pre-start response bound to the exact prepared context digest. A write-ahead `NativeDispatch` is not publication evidence because it is committed before the physical effect boundary.
3. `NativeStarted`: the native journal durably records the exact App Server turn identity.
4. `OutcomeObserved`: the native journal durably records a matching terminal observation.

Successful requests may advance directly from `AssignmentPrepared` to `NativeStarted`; the intermediate semantic boundary is not collapsed. Unknown socket outcomes, recovered write-ahead dispatches, and proven pre-effect aborts remain `AssignmentPrepared`, so they cannot become false exposures. Replaying the same assignment/native state produces the same receipt digest and no second ledger record.

`RetrievalAssignmentFact.delivered_candidate_indices` is an ordered sequence. Its vector offset is the serialized response position. Candidate-identity normalization remaps indices but must not sort the delivered sequence.

No fallible owner/provider operation is permitted after the durable assignment append. Publication and native consumption are derived only by joining the exact prepared context digest to the durable native journal.

## B — End-to-end execution boundary

A single request-scoped absolute deadline is propagated through provider acquisition, SQLite snapshot/observation, candidate admission, HNMF, downstream ranker, candidate and snapshot revalidation, text/context planning checkpoints, and learning append. Blocking ranker and ledger work use the same bounded executor as recall; they do not use an unbounded standalone `spawn_blocking` path.

The ordinary process bootstrap rejects provider timeouts outside `1..=800 ms`. Delivery capacity is two workers and shadow capacity is one worker with no waiting queue. A timed-out blocking worker retains its permit until it actually exits, preventing hidden oversubscription. These source bounds do not prove target-host CPU, RSS or allocation isolation.

## C — Product composition

The candidate composes:

- explicit proposition assertion/correction writers into the canonical memory owner;
- the signed retrieval context and independently challenged frontier already used by Agentd;
- the durable learning sink;
- a native-journal retrieval delivery verifier joining prepared context, server response, turn/start and terminal outcome;
- the ordinary Agentd process path rather than test-only object assembly.

Positive-weight Vector remains fail-closed in the ordinary bootstrap until an authenticated generation-bound encoder/index owner is separately composed and qualified. Lexical, graph, ranker or HNMF scores cannot be relabeled as Vector evidence.

## D — Exact candidate verification

The convergence workflow must test all three lanes:

- exact transformed source head;
- current `main` baseline;
- ordered-parent merge of fresh `main` and the exact transformed source.

Required checks are nonzero package tests, strict all-target Clippy, locked metadata, repository formatting, clean-source verification, Python transformer/contract tests, delivery crash-boundary regressions, deadline regressions, Vector rejection, and exact source/tree/parent receipts. Queued, skipped, cancelled, historical, or fixture-only results do not count as success.

The source publisher receives only a content-addressed patch produced by a read-only job. It does not execute checked-out repository code, does not restore candidate caches, verifies the exact input head and path inventory, and pushes non-force only when the remote branch has not moved.

## E — Target-host qualification and rollout

The checked-in SLO validator requires real `agentd-product` samples for all nine exclusive stages, at least 100 observations per pre-approved workload case, and measured request-scoped CPU, RSS, allocation and SQLite counters. It binds source head and tree and keeps `independentAcceptance`, `activation`, and `release` false.

The following evidence is mandatory and is not created by source CI:

- an instrumented production Agentd binary bound to its build receipt and executable digest;
- a target-host profile selected before viewing candidate results;
- a pre-approved workload matrix and numerical SLO policy;
- retained raw success, timeout, stale-rejection and failure traces;
- p50/p95/p99/max latency by total request and each of the nine stages;
- measured CPU, peak RSS, allocation and SQLite-read data;
- shadow, canary and rollback execution receipts;
- independently controlled external retention;
- explicit independent operator and reviewer acceptance.

Until those artifacts exist for the exact candidate, the only valid state is:

```text
productionImplementation = false
independentAcceptance = false
activation = false
release = false
```

No workflow, document, unit fixture, local benchmark, or assistant-authored threshold may change those values.