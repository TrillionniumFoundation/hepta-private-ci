# cognitive.store threat model

| Threat | Control | Required negative evidence |
| --- | --- | --- |
| Raw-store/capability bypass | read-only serving wrapper; unique Agentd facade; architecture gate | forbidden import/direct-write fixtures fail |
| Stale or replayed authority | grant digest, epochs, expiry, generation, live verifier | stale/revoked grant cannot advance cut |
| Valid-but-old backup rollback | independently retained exact current-cut witness | pre-tombstone backup rejected |
| Symlink/path/descriptor replacement | canonical path, `O_NOFOLLOW`, retained descriptors, exclusive fence | hostile identity cases reject |
| WAL/journal omission | descriptor-bound database/WAL/journal copy and checkpoint | crash/reopen exposes only committed predecessor/successor |
| Pointer publication ambiguity | atomic pointer + directory fsync; Indeterminate retirement | candidate is not deleted or reported inactive |
| Cross-Agent/workspace confusion | stable owner/scope identity and authorization before query | cross-owner and scope-escape tests deny |
| Intent/receipt replay with payload drift | semantic digest + stable intent identity | identical retry idempotent; changed retry conflicts |
| Provenance/source mismatch | same-transaction source revision/digest/time binding | canonical/durable mismatch rejects |
| Secret leakage | bounded content, redacted/digested evidence, no raw token persistence | canary secret absent from logs/receipts/exports |
| Resource exhaustion | content/count/page/journal/recovery bounds | oversize and maximum-retained profiles fail closed |
| Tombstone misrepresented as erasure | explicit lifecycle dispositions and ADR | docs/API never equate tombstone with media/model deletion |

New persistence, authority, export, federation or effect boundaries require threat-table and negative-test updates in the same change.
