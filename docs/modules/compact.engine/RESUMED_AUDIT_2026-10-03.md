# Compact checkpoint integrity continuation

Base: `df95fd5d087d813b0662a12e2b5a58770d5c31e8` (PR #1286).

## Confirmed findings

The legacy local-memory checkpoint seam was not covered by the stronger native
sealed publication protocol. Its checkpoint hash omitted the model receipt and
policy digests. Changing either could preserve a committed operation's identity
and be accepted as an idempotent replay. Imported loss reports were trusted by
their stored digest without recomputing it: omitted events could disappear and
an impossible loss score could be accepted with the old identity.

Follow-up review also reproduced imported duplicate/invalid protected references,
malformed summary/model/policy SHA-256 strings, and self-consistent leases with
invalid parent ranges, context IDs or fences. A matching lease hash alone does
not establish those structural invariants.

The correction validates the borrowed checkpoint fields at constructor, digest,
parent-admission and rehydration boundaries. It validates the parent/fence and
digest grammar locally, preserving other owners' contract types. Loss lists must
remain canonical, unique and bounded per identifier; the original loss digest is
recomputed. The checkpoint commitment now binds all three summary digests.

## Explicit compatibility boundary

- Newly constructed local checkpoints use envelope version 2 and the distinct
  `hepta-memory:compact-persistence:checkpoint:v2` hash domain.
- Hook/lease version 1 and persisted journal/event version 2 are unchanged.
  Historical event bytes, hashes, ordering and states remain readable for audit
  and normal store reopen. No SQL migration or row rewrite is performed.
- Old checkpoint version 1 is rejected for typed replay/rehydration. A new v2
  checkpoint cannot satisfy an old weak commitment under the original operation
  ID. No fallback, implicit upgrade or backfill is provided: old journals do not
  retain the omitted preimages needed to authenticate that transformation.
- Fresh reviewed operations may append v2 checkpoint commitments to the same
  historical journal. Consumers must retain old history and reconstruct new
  checkpoints from independently admitted inputs; a version-field edit alone is
  not a migration or a renewed receipt.
- Native `hepta-compact-engine` candidate and signed publication V1 contracts are
  separate from this legacy local-development checkpoint envelope.

## Verification and limits

The original failures were reproduced by compiling unchanged exact source. The
new registered regressions cover provenance swaps, changed loss data, invalid
digests and parent/fence fields, JSON roundtrip, unchanged append state after
rejection, literal historical journal reopen, and SQLite store reopen followed
by rejection of weak typed checkpoint use. Literal old-source fixtures avoid
regenerating historical hashes using the repaired implementation.

A scoped local full-memory build expanded into heavyweight dependencies and was
interrupted before disk exhaustion; it is not a package test result. Focused
exact-file tests and hosted full-package/platform results are recorded in the
continuation PR. The dedicated read-only gate executes the actual memory and
native compact packages on immutable source with existing ignored markers
retained. It does not bypass repository-wide lint or qualification failures.

At `ec5df7cf`, Linux executed all 374 native compact/memory tests successfully
(seven pre-existing ignored cases), including the real SQLite historical reopen
regression, then passed all-target compilation and formatting. macOS and Windows
failed early in inherited fixture setup: their temporary-root aliases were not
canonicalized before strict store admission. The shared fixture now canonicalizes
the directory it creates; production redirection rejection remains unchanged.

Windows also reproduced a migration line-ending defect. Independently applying
the 128-object schema inventory to LF migrations produces the required oracle
`046f23ba...`; CRLF checkout produces exactly the failing Windows oracle
`0d4c6e5e...`. A narrow Git attribute pins only this memory crate's SQL migrations
to LF. The required oracle, SQL content, migration versions and runtime checks
are not altered. Renewed final-head platform results remain a separate gate.

This closes local-development integrity defects only. A normal production
compact publisher, complete current-input membership in the owner's transaction,
immutable checkpoint body persistence/loading, selected CAS, final-use recovery,
independent COMPACT-01..04 evaluation and installed-host acceptance remain open.
No source-navigation update grants production authority, activation or release.
