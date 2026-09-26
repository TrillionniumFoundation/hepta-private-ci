# Schema migration compatibility matrix

| Transition | Read old | Write old | Roll back binary | Required evidence |
| --- | --- | --- | --- | --- |
| Same schema, newer binary | yes | after owner verification | yes | schema oracle, exact cut, package tests |
| Additive tables/indexes/triggers | yes after migration | new schema only | only if old binary ignores additions | migration checksum, reopen, rollback rehearsal |
| Semantic digest or authority change | adapter only | no dual write | no without explicit compatibility adapter | golden vectors, caller migration, fresh generation |
| Destructive/compacting migration | private generation only | after atomic publish | predecessor generation retained | prune plan, equivalence/non-resurrection proof |
| Unknown schema object or checksum drift | no | no | no automatic fallback | quarantine and operator recovery |

Migrations run under the single owner before readiness.  Required schema objects and their SQL are digest-bound.  A migration failure leaves the predecessor generation recoverable.  No route cutover may copy records into a second writable cognitive database.
