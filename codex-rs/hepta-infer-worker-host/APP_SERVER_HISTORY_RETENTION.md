# App Server history-retention contract

## Scope

The hosted native profile currently creates one ephemeral App Server thread per
durable inference request. This contract defines the minimum history behavior
required before restart reconciliation may be treated as an operational product
capability. It does not change the no-replay rule.

## Required retained identity

For at least the configured reconciliation horizon, the App Server owner must
retain an authenticated, immutable mapping for:

- Agent ID and generation;
- App Server version, protocol and Codex home identity;
- session and original connection identity;
- durable request/client-message ID;
- thread and turn IDs;
- exact original user input;
- model and model-provider identity;
- terminal status, ordered terminal items and terminal correlation;
- cumulative usage events when the provider supplied them.

`thread/read` must return one unambiguous matching turn or no result. Duplicate
matching turns, rewritten input, provider/session drift, missing terminal
correlation or conflicting usage are hard conflicts, not best-effort matches.

## Retention horizon

A deployment must select and publish a bounded history horizon based on the
largest supported worker outage plus incident-response delay. The horizon must
not be shorter than the maximum request timeout and must be measured on the
actual target host. Repository source intentionally provides no universal
production number.

Deletion is legal only after one of the following is durably established:

1. the native journal already contains a matching terminal observation and any
   required provider receipt has been archived; or
2. an externally governed permanent-unresolved disposition has been recorded,
   including the retained request/dispatch identity and capacity consequence.

Deletion, compaction, backup restoration or session rotation may never imply
that a missing turn was not sent.

## Recovery behavior

After worker restart:

- recovery uses only the original durable thread/request identity;
- `turn/start` is never called for an existing dispatch;
- unavailable history returns no evidence and leaves the operation
  indeterminate;
- exact terminal history may settle terminality;
- absent usage stays unknown;
- independently signed provider receipts are the only supported fallback for
  history loss or later usage refinement.

## Qualification

Target-host qualification must inject process death and history-service outage
at every boundary from durable dispatch through terminal usage. Evidence must
show bounded history, no duplicate provider call, deterministic conflict
handling, restore/rollback behavior and alerts before the configured retention
horizon is exhausted. A repository mock server is not target-host retention
qualification.
