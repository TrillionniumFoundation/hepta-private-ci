# Stable cognitive.store error catalog

Stable codes are operator/API classifications. Internal Rust messages may add detail but must not change the code's retry or security meaning.

| Code | Meaning | Retry | Operator action |
|---|---|---|---|
| `COG-INVALID-INPUT` | malformed id, scope, bounds, schema or unsigned bootstrap | no, until corrected | reject caller/configuration |
| `COG-ACCESS-DENIED` | owner/scope/grant/signature/token mismatch | no | inspect authority and trust |
| `COG-AUTH-EXPIRED` | signed lease expired | only after fresh signed state | rotate authority |
| `COG-AUTH-REVOKED` | live authority or signer trust revoked | no for this generation | stop writer; issue new reviewed generation if allowed |
| `COG-GENERATION-FENCED` | stale/regressed/skipped authority or writer generation | no | reconcile signed chain and active owner |
| `COG-REVISION-CONFLICT` | expected Memory predecessor is stale | reread then recompute | obtain current head; do not blind retry |
| `COG-ALREADY-TOMBSTONED` | mutation attempts resurrection/redelete outside idempotent receipt | no | preserve terminal state |
| `COG-CAPACITY` | bounded record/journal/page/profile capacity reached | policy-dependent | archive/reconfigure through approved generation |
| `COG-UNAVAILABLE` | safe pre-admission storage/resource failure | bounded retry | inspect resource/host health |
| `COG-CORRUPT` | schema, lineage, digest or invariant failure | no automatic retry | isolate and run trusted recovery |
| `COG-INDETERMINATE` | publication/effect may have occurred and truth is unresolved | reconcile only | preserve evidence; no replay |
| `COG-RECOVERY-STALE-CUT` | candidate differs from independently retained current cut | no | locate current generation/witness |
| `COG-RECOVERY-IDENTITY` | redirected, replaced or changing filesystem identity | no | secure host storage and repeat ceremony |
| `COG-MIGRATION-INCOMPATIBLE` | database newer/unsupported or rollback binary incompatible | no | upgrade/roll forward |
| `COG-PRIVACY-PENDING` | logical delete committed but physical/derived owners incomplete | reconcile | continue owner disposition campaign |

## Mapping discipline

- `Invalid` maps to `COG-INVALID-INPUT` unless authority-specific.
- `AccessDenied` and signature/token mismatch map to `COG-ACCESS-DENIED`.
- CAS/conflict maps to `COG-REVISION-CONFLICT`.
- `Corrupt` maps to `COG-CORRUPT`.
- `Unavailable` is retryable only when the operation is known not to have crossed admission.
- recovery `Indeterminate` and post-effect uncertainty always map to `COG-INDETERMINATE`.

Logs and receipts include code, operation id, owner/scope digest, generation/revision and safe cause class. They never include raw authority token, secret, prohibited payload or signing key.
