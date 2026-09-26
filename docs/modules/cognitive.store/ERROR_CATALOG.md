# Stable error catalog

| Code | Class | Retry | Operator action |
| --- | --- | --- | --- |
| `COG_INVALID_INPUT` | rejected | no | correct bounded/versioned input |
| `COG_ACCESS_DENIED` | security | no | verify owner/scope/authority; do not downgrade |
| `COG_REVISION_CONFLICT` | concurrency | after reread | reacquire head and issue a new intent |
| `COG_WRITER_FENCED` | security/concurrency | no on same generation | obtain newer externally verified generation |
| `COG_AUTHORITY_REVOKED` | security | no | stop writer and reconcile committed outcomes |
| `COG_STORE_UNAVAILABLE` | availability | bounded before admission | preserve existing cut; alert on SLO breach |
| `COG_STORE_CORRUPT` | integrity | no ordinary retry | descriptor-safe recovery ceremony |
| `COG_RECOVERY_STALE_CUT` | rollback protection | no | supply authenticated current witness |
| `COG_RECOVERY_INDETERMINATE` | integrity | no automatic retry | reconcile active pointer/candidate manually |
| `COG_CAPACITY_EXCEEDED` | resource | no blind retry | page, archive under ADR, or increase qualified profile |
| `COG_EXTERNAL_EFFECT_INDETERMINATE` | effect truth | observer only | reconcile destination; never redispatch blindly |

Rust variants remain the typed source of truth.  Adapters map them to these stable codes without parsing display strings; messages may change, codes and retry classes may not change in place.
