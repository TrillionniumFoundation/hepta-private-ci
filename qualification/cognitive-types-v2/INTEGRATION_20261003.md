# Current-main integration follow-up

This increment integrates main `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`
into the existing cognitive.types convergence branch. It does not change the
canonical cognitive.types source, V1 wire/digest profiles, or the shared-experience
context-v3 framing. Current source identity is the PR head, not a self-referential
identifier embedded in this document.

## Conflict resolutions and preserved policies

- Preserve strict `-D warnings` qualification and retained per-command evidence
- Keep automatic HNMF pull-request and main-branch path coverage. No aggregate
  caller for the reusable HNMF workflow was found; `workflow_call` is additional
  and cannot replace the automatic triggers. Regression mutations reject a
  reusable/manual-only replacement or loss of either automatic event
- Keep version-matched HNMF lock checksums, verified against the official sparse
  registry, rather than pairing newer versions with older main checksums
- Use the central durable SQLite profile for AuthBus while retaining its
  non-authoritative in-memory schema oracle
- Preserve the operation/destination owners' original four-connection bound.
  The generic evidence profile remains five connections for existing consumers,
  including AuthBus. The explicit operation-owner profile and canonical-parent
  adapter reuse reviewed integration `3c516ec10e753a2709000da45e581cd66a30ef55`
- Preserve historical navigation anchors and all execution/acceptance boundaries
  when binding changed source. A new source observation transfers no qualification

## Newly covered integration regression

The first conflict resolution accidentally selected the generic five-connection
profile for both operation constructors. Existing regression tests passed without
covering that resource-policy difference. Two added tests exercise the actual
`DurableOperationStore::open` and `DestinationDedupeStore::open_standalone`
constructors. Both compiled and failed with actual `5 != 4` before the correction;
the same two tests passed after the explicit operation-owner profile was restored.

The tests inspect WAL, FULL synchronous mode, enabled foreign keys and a 5000 ms
busy timeout on all four simultaneously leased connections, then check that no
fifth lease is available. They do not substitute a stand-in pool constructor.

## Evidence boundaries

Local scoped checks are not hosted exact-head, synthetic-merge, target-host,
independent approval, production activation or release evidence. Two Python
resource-wrapper tests require the unavailable `/usr/bin/time`; no replacement
wrapper is treated as qualification. `just bazel-lock-update` could not run because
Bazel is unavailable. These limitations remain explicit rather than changing the
required gates or claiming results from a previous source head.
