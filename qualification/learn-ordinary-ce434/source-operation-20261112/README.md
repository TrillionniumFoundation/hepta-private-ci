# Original Source operation — fixed source review

This change reduces repeated Source reads inside one occupied original Training/Model lane. It creates no signing, selection, publication, FinalUse or task-execution authority. Ordinary A/B/C and daemon/Root restart acceptance remain **0**.

## Fixed ancestry and status

The Source baseline is a8e8e5544b000da2942deba96ed855791c4af104. The source-only checkpoint is e2c0a3dd1fa86ccddc47ea83b2a7402761bd5e37 (tree 95a266099902a5dc320c8c0f1c299e49fca6db1b); all 11 immutable Rust blobs were read back byte-for-byte. This evidence accompanies the next guard/inventory commit.

No Rust formatter, compiler, Python suite, native mechanism, or full-repository caller verifier was executed by this agent. JavaScript checks are limited to source lexical order, explicit typed callers in changed production files, and complete-record accounting. They do not prove compilation or ordinary deployment.

## Production behavior

The original native owner retains its sealed Source in a private Arc. Each original lane borrows that same Arc and begins a non-Clone, non-Deserialize operation. Begin performs one real Experience, Dataset, and Material read. Actual native Training/Model work then runs under the same original semaphore and owner mutex. The operation performs one real after read of each source, compares the complete material and exact signatures, and checks Source, immutable config, and loaded baseline Arc identity.

The lane physically rereads native and Generator CURRENTs after the source I/O. Finish consumes the operation only after those reads and fresh authentication of the retained Experience/Dataset signatures and the original Freeze signature/producer. It never creates a new validity window.

An unfinished operation's Drop fences its original Source. A cancelled SourceBound async waiter still leaves the blocking worker holding its original permit; cancellation fences the same original stage even if the worker has already finished its physical work. Existing legacy stages without Source retain their original cancellation behavior.

Candidate material and SourceBound admission receive only the private proof from this same invocation. A boolean, saved digest, earlier request, different Source Arc, or caller-supplied future cut cannot replace it.

## Preserved native withdrawal semantics

The existing current_material, fit_or_readback, and require_original_source_capture function bodies are byte-identical to the baseline. Standalone current_material still reads every source twice. The native trainer still checks source before fit and after optimization, before completing its native journal. The stage's pre-sign source check remains. The existing real withdrawal-after-claim mechanism therefore retains its Pending/no-Generator-signature gate.

## Request accounting

Counts below are per original Experience, Dataset, and remote Material channel. One network request/response exchange comprises two directional frames.

| Path | Reads per channel |
|---|---:|
| Independent full capture/current API | 2, unchanged |
| Completed Training readback lane | 2, previously 4 |
| Model lane | 2, previously 4 |
| Candidate material lane | 2; the extra inner full capture is replaced by the same borrowed proof |
| First Training execute | 8: lane 2 + native prefit 2 + native post-optimizer/pre-complete 2 + stage pre-sign 2 |
| Production Training bootstrap minimum | 10: capture 2 + explicit bootstrap current 2 + original Stage admission 2 + SourceBound admission 2 + command-owner context 2 |

The bootstrap minimum excludes Execute, later Ready/readback, downstream calls, and external launcher behavior. The complete 128-request budget is not claimed closed by this change.

The Source remote Material protocol is a single full response, bounded to 16 KiB. It has no Begin/Page/Finish protocol and no paging fallback. Actual response bytes have not been measured. Candidate heads use a different protocol owned by the Model change; two actual Candidate material calls each perform their own complete two-read source interval. Local Material reads are actual Source/Ledger I/O rather than a Material network exchange.

## Boundary and guard accounting

This commit adds 16 private boundaries and their inventory IDs, tightens 2 old caller lists, adds 8 complete protected records, and updates 9 complete existing protected records. The baseline 528 boundaries become 544; the baseline 384 protected records become 392. No path-based deduplication is used.

The affected source check covers 27 complete protected records, 75 non-generic function guards, 13 global order sequences, and 3 additional function-scoped generic guards. The generic guards live in the new source QA because the unchanged verifier's function_order syntax accepts non-generic function names. Its core implementation and RootAdmin rules remain unchanged.

Four older QA files receive only the necessary source/proof marker and exact-caller changes; reversing those edits restores every other byte. The new QA contains eight methods. None of these Python tests has been executed here.

See source-audit.json for complete old/new records, new metadata IDs, all declared caller sets, exact QA edits, and the explicit limits of each check.

## Native mechanisms awaiting execution

Five new real-owner mechanisms are authored in cell_q24_training_source_operation_tests.rs:

1. Actual Candidate fit, original Generator receipt, Model owner initialization, Candidate material and completion rereads; exact Experience/Dataset fixture transport totals are asserted at 20 each.
2. Actual Source withdrawal while native readback is gated after the Source before read; the result must be uncertain, fenced, and leave completed native/Generator bytes unchanged.
3. Cancelled async waiter while native witness I/O is blocked; the permit remains occupied, then the SourceBound stage is fenced.
4. Byte-identical captures with different Source/config Arcs cannot exchange a private operation proof.
5. An unfinished operation after a real durable native completion fences the owner, preserves the bytes, creates no Generator claim, and permits only the original journal's explicit cold recovery.

These are explicit same-UID fixture mechanisms. Their expected counts are authored assertions, not observed results. They do not establish external role-host custody, ordinary Root registration, independent B retention evaluation, positive adoption, distinct-input fresh-session C, or a daemon cold restart.
