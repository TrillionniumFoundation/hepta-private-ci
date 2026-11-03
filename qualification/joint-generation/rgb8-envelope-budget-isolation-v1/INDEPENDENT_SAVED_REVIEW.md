# Independent saved-result review — PASS

Reviewer /root/review_risk_decomposition. Read saved JSON/logs and source; independently verified hashes, observation inventory, primitive budget relations, parity-hash consistency and receipt arithmetic. No adapter/test/worker execution, model or dataset use, tensor reconstruction or historical file mutation.

## Exact provenance and completion
Final FREEZE SHA256 `0cc4f7e0c096c3c60dfee08a04c4f6977d975f58a6ff0897d119c52c01b5d187`; RESULT SHA256 `e0ebcf91aaa996443898ea0696125fc3222fde4bb02078a3b706147e47154bd3`. Match receipt/current bytes; all25 frozen source/history hashes match. Frozen legacy copy and one-line fixed adapter, already-fixed contracts and authentic encoder dependencies remain as source-admitted. Receipt complete_wait true, exit/raw status0, no timeout/retry; stderr5/5 tests pass. Expected refusals are part of fixed qualification, not retries.

## All28 retained observations
- Two preserved legacy observations, one per budget field: saved primitive before/after matches the old behavior and runtime identity assertion.
- Four fixed-isolation observations, both fields and directions: independently checked saved before/envelope/request/sibling/fresh dictionaries. Returned-request changes leave parsed envelope and sibling values unchanged. Later envelope changes leave old request values unchanged; a fresh conversion reflects the new declared value. Before values5000 compute/4096 bytes and resulting per-field snapshots reconcile exactly. This confirms bounded value isolation, not immutability of returned requests or protection against arbitrary local code.
- Eight parity observations cover exactly two commands ×two decode modes ×two stream orders. Saved hashes have exactly two feature identities by command and four request identities by command/mode; reversal of stream order does not change either. Runtime source/assertions check old/new request equality, real encode_request exact array equality, shape1×202 and expected ten instruction coordinates. Feature tensors and full requests are not saved; reviewer did not reconstruct them and does not claim independent tensor or model parity.
- Twelve expected refusals cover both implementations ×all six fixed admission cases. All budget-unchanged flags present. Those cases call adapters, not callbacks; callback nonexecution on rejection follows source ordering rather than a separately instrumented dispatch test.
- Two actual dispatch observations each record one local literal callback; fixed envelope remains unchanged, legacy behavior retained separately. These callbacks are not model inference, external owner callbacks or live backend execution.

## Ledger and full costs
42 adapter attempts =30 success+12 expected refusal.48 actual encoder attempts =46 success+2 unknown-word refusal, including16 direct parity calls.28 observations and2 callbacks reconcile. Forbidden model/dataset attempts0. Original model/data modules were imported for authentic dependencies, but no model allocation/loading/inference/training or dataset generation occurred under reviewed paths/guards. Import cost is included, not zero.

Whole-child CPU **0.164622s** =user0.148310+system0.016312; wall0.185622639983s; maxRSS28752KiB. RESULT CPU prefix0.123443970 is not total. Supervisor observed prefix0.002725896 plus unknown nonzero final tail and source/preparation/review/upstream work are additional. Limits5CPU/30wall/512MiB/4MiB-file; CPU0/one numerical thread, existing synthetic-only lock, fullwait/no retry.

## Scope
PASS supports the isolated trusted-local RGB8 TEXT+IMAGE adapter's budget value-copy regression while preserving encoder behavior/admission in the fixed cases. It is distinct from the previous RunSpec.payload repair. No deployment or latest Fashion active-path integration is demonstrated; current Fashion runtime was not shown to call this old RGB8 adapter. No production authority, authenticated boundary, arbitrary hostile-code/FS protection, model quality, scientific-gate improvement or lifting of any prior hold follows. Historical immutable source/results remain unchanged.
