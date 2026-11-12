# Fresh2 final-format records: exact-byte recovery

The original native job `1a1d1cb5f1a-2564-1c7c` completed normally with exit 0.
Its pinned RESULT records the approved 11 non-Rust applications, one original
900-second fmt command returning 0, zero formatter-induced changes, and three
verified final audits. No test command or fix was dispatched. This package
recovers the exact large records of that already completed operation; it does
not run or repeat that operation.

## Inputs and recovery boundary

The independently read RESULT, normal supervisor SDK and ARTIFACTS supply all
target identities. The exact earlier SH73 bytes, its complete original V5
inventory, the reviewed V2 11-file before/after packet and the final complete
inventory supply the record contents. The final inventory had first been an
offline candidate; it is accepted here only because its whole 5,614,896 bytes,
SHA256 and Git blob match the actual native ARTIFACTS and RESULT.

`recover_actual_records.py` reconstructs the original V5 transition JSON with
the original sorted compact UTF-8 JSON plus LF serialization. It reads the V5
source to pin and retain the exact constructor/serializer text; it does not
import that module or execute any of its code. All source files remain
untouched. Every one of the 11 before files also equals its actual SH73 bytes.
Every one of the 11 after files equals the reviewed packet and actual final
inventory row. The other 15,177 rows remain byte-for-byte unchanged between
these two complete inventories.

The recovered records are:

| Original record | Raw bytes | Raw Git blob | Changes |
|---|---:|---|---:|
| apply.after.postimages.json | 4,392,239 | 8fe1469de132ccddae81b36582857816f6eea659 | 11 |
| fmt.after.postimages.json | 438 | b9cbaf207c5e85cc5e697486c4ae473f15ae00b1 | 0 |
| final.postimages.json | 4,392,233 | c04295e4887536ce8ccc97cb3ff9d5f0feb6735f | 11 |
| final.inventory.json | 5,614,896 | 445e54a43503dd79ba1e856e2e07acf532994ae6 | complete 15,188 leaves |

Each raw file, its original gzip encoding, and every original base64 part
matches all three independently observed identities: byte length, SHA256 and
Git blob. The raw JSON of apply/final differs in its original stage name; those
records have not been merged or renamed into one outcome. The small empty-fmt
gzip also equals all 276 bytes returned by the separately retained actual
native binary-read SDK at its fixed version. That is a direct-read anchor for
that one small file, not a claim that the larger files were read again.

## Reconstruction

For each output, take its `parts` array in RECOVERY_REVIEW order. Base64-decode
each part independently, concatenate the decoded bytes by `decoded_offset`,
and verify the whole gzip length/SHA256/Git blob. Decompress it, then verify the
raw length/SHA256/Git blob. Each part itself has its original independent pin.
All transport files are below 500 KB. The 14 logical parts use 11 unique Git
blobs: apply and final share their first three original gzip segments.

Six original inventory names (apply/fmt/final, before and after retention) have
the same complete raw and compressed bytes. `inventory_exact_aliases` gives
every original name and its exact mapping to the retained five inventory
parts. This is an equality proven against each original ARTIFACTS entry, not
an omission of an observation or a replacement serializer.

Three small postimage-summary records are recovered independently from the
actual RESULT with the same exact serializer and checked against their own
ARTIFACTS pins. The original HEAD-working patch itself is not recovered by this
package; its observed length and hash remain in the summaries.

## Preserved limits and failures

This is exact reconstruction against an original identity, not a second native
full read or a new native execution. The actual three failed transport
observations for initial RESULT/status/stdout reads remain unchanged and are
listed with their original hashes in RECOVERY_REVIEW. Their later successful
reads and normal producer terminal do not erase those transport failures.

The source still has detached HEAD `9c4a11f61d30e9cc352bf44d56c98909d202a55d`
and index tree `ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7`; the full inventory
preserves its actual dirty status. Physical tree
`d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087` is an observed materialization,
not evidence that canonical alignment or any qualification gate has run.
No H call, Cargo invocation, source main, formatter, test, source write, ref
update or approval change was made to produce this recovery package.
