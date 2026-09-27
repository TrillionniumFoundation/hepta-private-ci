# control.runtime V11 convergence

This document records the implementation candidate on branch
`codex/control-runtime-v11-convergence-20260928`. The machine-readable source of
current claims is `CURRENT_STATE.json`. The existing `TECHNICAL.md` remains the
long-form target guide; it is not an activation or release receipt.

## 1. Closed-world planner admission

The public planner boundary rejects owner summaries outside the declared required
owner set. An optional owner can no longer shorten snapshot expiry or poison the
missing/stale/unavailable masks unless a future protocol explicitly admits an
optional-owner set. Duplicate final-payload digests now reject before the legacy
canonicalizer can collapse them.

## 2. Authenticated cognitive-context planning

The Agentd compatibility path remains byte-compatible. After the canonical owner
read, Agentd constructs an authenticated record set from exact record ID,
revision and content digest. `control.runtime` derives the verified record count
from this set rather than accepting an independent scalar assertion.

The authenticated request binding covers owner, Agent generation, query bytes,
result limit, request ID, owner snapshot/read identities, current retrieval
execution context and the selected ranker policy. The authenticated plan is kept
alongside the existing wire receipt in a bounded process-generation registry.
Final use requires:

1. the exact previously published wire receipt;
2. an unexpired process-monotonic lease;
3. unchanged retrieval-context identity;
4. unchanged ranker-policy identity;
5. successful canonical owner-cut and exact-record revalidation.

A process restart drops the registry and therefore invalidates historical context
packets. This is fail-closed and matches the Agent generation fence. The wire
shape is deliberately unchanged; protocol admission of a new externally visible
authenticated receipt is separate work.

## 3. Maturity split

`control.runtime` is tracked as four separate source surfaces:

- bounded global planner;
- authenticated request-local context adapter;
- read-only organ host;
- embodied-control qualification references.

A source-composed Agentd read caller does not imply a global planner production
caller. Neither the read-only caller nor a deny-all grant request establishes a
production writer, capability issuance, effect execution, operator acceptance,
activation, promotion or release.

## 4. Qualification

The NDU workflow splits each regression family into its own step and runs the
control-plane/Agentd request-integrity tests, all-target compilation, strict
Clippy, formatting, exact source-head and deterministic synthetic-merge lanes.
The state manifest remains `pending_exact_head` until one immutable candidate has
completed all of those checks.

## 5. Remaining production work

The next source layer is a versioned single-writer `PlannerStoreV1` and a named,
authority-separated execution coordinator. Production claims remain false until
crash/restart, disk-full, partial-write, backup/restore, overload, revocation,
final-payload drift, fan-out reconciliation and target-host tests have current
receipts. Independent semantic review, canary and rollback rehearsal are external
gates and cannot be self-issued by this repository candidate.
