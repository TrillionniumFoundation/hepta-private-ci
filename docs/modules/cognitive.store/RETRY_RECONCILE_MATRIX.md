# Retry and reconciliation matrix

| Point of failure | Mutation possible? | Allowed next action |
| --- | ---: | --- |
| Before SQLite admission | no | bounded retry with identical intent identity |
| During transaction before commit | no after rollback | identical retry after store availability |
| Commit returned success | yes | return/query committed receipt; changed retry conflicts |
| Response lost after local commit | yes | query occurrence/provenance; do not create a new intent |
| Before external final-use entry | local queue only | renew bounded claim or release safely |
| After possible external entry | unknown | mark Indeterminate and observer-only reconcile |
| Authority revoked before mutation | no | reject; obtain a newer grant/generation |
| Authority revoked after local commit | yes | preserve commit; revoke future use |
| Active-pointer rename/fsync ambiguous | unknown active generation | no cleanup; mark recovery Indeterminate |
| Restore older valid backup | would resurrect | reject by exact current-cut witness |

Backoff, claim lifetime and batch size are bounded configuration.  Reconciliation never treats queue acceptance, process exit or timeout as destination success.
