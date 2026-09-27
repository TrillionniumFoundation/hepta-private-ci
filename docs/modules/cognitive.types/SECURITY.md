# cognitive.types security model

This document describes validation and integrity controls. It does not grant repository, runtime, deployment or data-access permissions.

## Protected properties

The module protects cognitive content and provenance, scope and privacy labels, write-intent bindings, snapshot and generation identities, learning proposals, canonical bytes, digest profiles and consumer comparison evidence.

## Threat/control matrix

| Risk | Control |
|---|---|
| payload substitution | full intent, candidate, approval-context, fence and snapshot binding in the canonical receipt |
| stale retry under a different generation | fence digest plus generation checks at the state owner |
| fabricated rejection record | tagged rejection with no record fields |
| schema confusion | closed schema/version/contract registry |
| canonicalization ambiguity | exact canonical-byte equality |
| Unicode normalization collision | code-point preservation profile and cross-language vectors |
| oversized or expensive input | byte caps, collection caps and bounded selector indexes |
| contradictory fields | strict cross-field validators |
| malformed or missing selector target | RFC 6901 checks plus digest-bound selector-resolution context |
| consumer boundary confusion | consumer and direction-specific registry binding |
| false comparison match | comparison state derived from both digests; only exact equality qualifies |
| accidental capability inference | contract values retain `DENY_ALL`; the state owner performs independent checks |
| deleted-state reappearance | durable lineage, tombstone and recovery checks at the state owner |

## Non-claims

A valid contract does not prove caller identity, permission, current revocation state, asset access, selector existence without a resolution context, source completeness, durable persistence, external side-effect success, application activation or release approval.

## Receipt signatures

The current strong receipt is digest-bound. A deployment requiring signed receipts must introduce a separately reviewed schema that binds signer identity, key generation, validity interval, revocation state and verification algorithm. The digest field is not silently reinterpreted as a signature.

## Safe evidence

Safe evidence contains schema ID, version, contract ID, bounded error code, field path, payload byte count and digest. Raw cognitive content, credentials, approval material and private provenance are excluded.

## Mandatory review triggers

Review is required for a new capability-bearing field, network or filesystem access inside the type crate, dynamic schema registration, relaxed size limits, normalization changes, signature/key semantics, application write/effect invocation or changed retryability semantics.
