# Authentic N256 compact full-state checkpoint stage

Status: **HOLD / all_closed=false**.

This separately frozen stage addresses the storage blocker exposed by the ten
authentic index256 originals in #6944/#6945. Their canonical exact-fraction JSON
states occupy 62,877,713 bytes in aggregate, leaving only 4,231,151 bytes under
the existing 64 MiB aggregate cap before the first possible tail check at index
537.

The candidate container is lossless and bounded. It accepts only canonical
full-state JSON with exact schema/index/body-hash/source/parent/lane bindings,
uses a fixed 8 MiB LZMA2 dictionary in an XZ stream with SHA-256 check, and adds
fixed raw/compressed lengths plus raw/compressed SHA-256 digests. Decoding caps
the compressed input at 8 MiB and decompressed output at 32 MiB before accepting
the restored canonical state.

The sole admitted hosted run may only transform the ten already-published
index256 originals, encode each twice to establish byte determinism, decode each
once, and compare the restored bytes directly with the immutable original. It
executes zero recurrence row actions, tail checks, provider outputs, dynamics,
matrix exponentials, Torch calls, optimizer steps, models, or training work.

Success closes only an index256 lossless compact-full-state serialization and
resource measurement. It does not predict index537 size, execute index537,
certify a tail or unique rounding, admit a provider, establish arbitrary-history
resume, qualify N256, close C2 full replay, provide HPCA external custody, or
adopt production. #6939 remains RED; #6942 remains RED_TIMEOUT with completed
row actions UNKNOWN; #6901 remains UNKNOWN. Historical negative and UNKNOWN
records are unchanged.
