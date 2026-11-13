# Exact recovery of the actual 1c98 postimage records

This package restores the exact original `apply.after`, `fmt.after`, and `final` transition records from native job `1a1d2107dce-2564-1c98`. Every complete raw JSON identity, complete gzip identity, encoded part identity, decoded part hash, size, and offset matches the independently observed `ARTIFACTS.original.json`. This is offline lossless recovery, not a second native full read or a new execution.

The actual source remained at commit `246d8cb614770252ee42029a5c014f2a4904176a`, index tree `d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087`. Five reviewed non-Rust files changed in the working source, producing physical tree `b7b357c07b5539769a068c6b9b009629f5612d1e`. The original formatter returned zero and made zero additional changes. The other 15,183 complete inventory rows are unchanged.

## What was matched

| Original record | Raw bytes | Raw Git blob identity | Gzip bytes |
|---|---:|---|---:|
| `apply.after.postimages.json` | 4,415,767 | `3ebf5dedc638cc8c65b71ccb53f78b22bb5830c9` | 850,117 |
| `fmt.after.postimages.json` | 438 | `66d6aa5c12fe22f97f722d6efecc9ef7d15f9cf2` | 276 |
| `final.postimages.json` | 4,415,761 | `541a5f702cea20ebba5cbeee2f30fcc34593ce77` | 850,111 |

The three initial gzip parts of `apply.after` and `final` are identical. Their final parts differ. Five unique large-record parts therefore restore both large original records. A sixth, small part contains the empty formatter transition and also matches an actual complete native read of its 276-byte gzip.

`MANIFEST.json` maps every original part name to one stored, immutable base64 file. For each original record separately, use the listed order, remove the single terminal LF from each part, base64-decode each part, concatenate the decoded bytes, verify the complete gzip size/SHA256/Git identity, gunzip once, then verify the complete raw JSON identity. Do not reserialize the restored JSON.

## Inputs and reproducibility

`RECOVERY_REVIEW.json` binds the actual RESULT, ARTIFACTS and normal supervisor bytes; the complete before and after inventories; all five original and changed source byte identities; and the exact original V5 serializer functions. `recover_postimages.py` reads only these local retained inputs, performs the original deterministic serialization and gzip operation, and refuses to retain a record as exact unless every original identity matches. Archived source/control modules are parsed for provenance and are never imported or executed.

The complete inventories are reused from their existing packages. This package does not duplicate ordinary_path's 30-file inventory/canonical preparation. Large raw JSON and gzip Git identities are recorded because they match the actual ARTIFACTS; their existence as independently uploaded Git objects is not asserted. The bounded base64 companions carry all bytes needed to reconstruct them.

## Limits

The old source qualification failure is preserved. These recovered maintenance records confer no source-gate, native-test, Root-test, or real-task qualification. No H call, formatter, Cargo command, test, source edit, ref mutation, or new source observation was performed by this recovery. The earlier 3033-file preparation and its 23:28:14.670813 UTC cutoff remain unchanged. This package is a separate optional increment for Root to review and publish.
