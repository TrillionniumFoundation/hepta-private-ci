# Retry and reconciliation matrix

| Boundary | Safe state | Retry rule | Reconciliation source |
|---|---|---|---|
| Bootstrap file read/parse before recovery | no store effect | retry same immutable files after host I/O recovery | file identity and signature |
| Bootstrap signature/token mismatch | denied | no retry without corrected externally signed bundle | signer trust and token digest |
| Writer recovery before active pointer publish | predecessor remains active | retry only with same current witness and authority if failure is explicitly unavailable | recovery files and active pointer |
| Active pointer publication ambiguity | unknown active generation | never ordinary-open or recreate | active-pointer and candidate-generation inspection |
| Semantic validation before transaction | no mutation | correct request then retry | validation error |
| `BEGIN IMMEDIATE`/capacity failure before commit | no committed occurrence | bounded retry with same intent identity | SQLite transaction and operation status |
| Revision CAS conflict | another head won | reread and recompute; new semantic input/intent | current Memory head |
| Commit succeeded, response lost | mutation may exist | no blind replay; query stable operation/receipt | local event/outbox and Memory/source ids |
| Live revocation before mutation | denied | only a fresh signed grant/generation may proceed | signed authority state |
| Revocation after committed mutation | historical commit remains | do not undo or replay | committed production receipt |
| Outbox destination unknown after entry | `Indeterminate` | observer-only reconciliation | destination idempotency/observation API |
| Export cut changes before publication | stale export | restart from new cut or return stale | current snapshot digest/frontiers |
| Logical delete response loss | tombstone may exist | reconcile head/receipt; do not issue independent tombstone | Memory head and operation status |
| Archive upload acknowledgement loss | content may exist | query by segment digest; upload only identical bytes | archive object digest |
| Migration/rebuild before publication | old generation active | retry private generation build | pre-upgrade cut and migration receipts |

## Backoff and budgets

Retries are bounded by the caller's absolute deadline and resource budget. Exponential backoff never converts denied, corrupt, conflict or indeterminate outcomes into retryable ones. A retry preserves stable intent identity only when semantics are identical; changed semantics require a new identity and fresh authority binding.

## Restart ordering

1. authenticate current signed witness and authority state;
2. resolve active-generation ambiguity;
3. open/recover the exact store;
4. reconcile committed/indeterminate local operations;
5. revalidate revocation and writer generation;
6. admit new writes.
