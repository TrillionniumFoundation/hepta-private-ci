# Controlled native v1 continuation and v2 shadow: complete evidence

Both local engineering runs completed successfully at source `3a1431c5879d084bf49b9df67f9792af8f3acbc7`. The checkpoint was trained once under `8a47cdd26574a85cd314fabce65cc395dbe316a8`; its original predecoder failure remains separately published. This package freezes the completed runs and the current program report. Later formatting, Clippy and CI belong to separate evidence.

## Observed model execution

| Phase | Decoder queries | Explicit feature forwards | New training | Model child processes |
| --- | ---: | ---: | ---: | ---: |
| Original failed attempt, referenced separately | 0 | 0 | 96 updates / 96 training forwards | 1 |
| Successful v1 continuation | 3 | 1 | 0 | 3 |
| Controlled v2 shadow | 1 | 1 | 0 | 1 |

The native v1 and v2 outputs are both `order`, with generated token IDs `[2559, 2]`. The base and shuffled controls each failed this single observed case. These are reads of one already exposed case using the same checkpoint; future tasks remain 0 and future accuracy remains null. The two controls test parameter participation, not superiority to a strong retrieval system. No fresh training or model acquisition was performed by the successful runs, and no model was run for this archive or its audits.

V1 exercised the actual Agentd control socket and native model port. V2 exercised the direct owner, `tick_shadow`, v2 request binding and durable journal/witness. Its two owner recoveries occurred within the same process; its source-supported delivery was subsequently refused after the actual tombstone without another callback. V2 retains `abstain=true`, no authority grants, `calibration=null`, controlled context, no production Objective/NDU provider, no default daemon installation and no v2 control-socket claim. Physical parameter erasure and independent operational witness trust are unqualified.

## Complete preserved bytes and costs

| Artifact or resource | Observed quantity | Accounting scope |
| --- | ---: | --- |
| V1 completed run | 5,611 files / 93,394,724 B | Entire directory retained, including actual private-home runtime resources |
| V2 completed run | 57 files / 6,081,243 B | Entire directory retained, including journal, witness, SQLite files and process evidence |
| Checkpoint copy | 1,890,112 B | Included in v1 file total; original weights unchanged |
| Shared six-file base | 271,170,520 B | All size/SHA pins rechecked; bytes excluded from publication |
| Base scalar parameters / adapter scalars | 134,515,008 / 460,800 | Independently counted from safetensors headers |
| Runtime FP32 parameter bytes | 539,903,232 B | Base plus adapter, not adapter-only accounting |
| Native v1 / v2 peak process RSS | 1,131,851,776 / 1,131,753,472 B | Distinct observed worker peaks; not additive simultaneous peak RAM |
| V1 / v2 executable files | 479,626,376 / 76,125,400 B | Exact build/invocation SHA receipts; binary bytes excluded |
| Original failed / v1 / v2 wrapper wall | 77.662583296 / 36.856582231 / 14.816371575 s | Three distinct measured attempts |
| Sum of those wrapper times | 129.335537102 s | Includes original failed training once; nested timing not added again |

The two completed run trees contain 99,475,967 regular-file bytes, plus their directories. Their reported filesystem allocation is 107,094,016 and 6,225,920 bytes respectively; shared-base allocation is 271,187,968 bytes. File length and `st_blocks` are distinct measurements and do not establish exclusive physical-device use. Full system storage, quality-matched net compression and sustained throughput remain unqualified. Excluding base and executable payloads from publication does not erase their costs.

The original failed run is retained at [fixed published evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9f511ed8fd13aab7c6ee56709d46c61a1af05c2c/qa/stem-bakeoff/evidence/20261025-native-predecoder-failure). Its complete archive SHA256 is `99c1c0e21eaf246812ab20f93ce12db2eac3a5dbf77ac861068b11724dbbcf07`; that large archive is referenced, not copied into this package. Reused source/checkpoint bytes inside the new v1 run remain part of its actual retained state.

## Qualification and independent audits

The package includes test007 (224 Agentd tests passed, 6 skipped), build002, exact-candidate-alignment002, runtime freeze, both outer wrappers and drivers, resume source and admission reviews. The tested 9,721-file map is unchanged and a subset of the 9,729-file build map. The source bridge accounts separately for two subsequently added Python drivers, six restored published evidence files and the one symlink-text versus followed-content hash representation. Historical helper-preflight001 used the earlier 8a47 binary and is not relabeled as a new helper run. The final formatted-source CI is pending in this immutable snapshot.

The independent general audit passed 72 checks. The independent actual-shadow audit passed 134 checks, including recomputed request/source/profile/namespace/production-receipt bindings and the actual journal/witness checksum/anchor chain. Their raw JSON and standard-library audit scripts are included. They performed no model execution, SQLite open or independent kernel reexecution. The program report and eight-gate snapshot are retained byte-for-byte; all eight `full_closure` flags remain false.

## Integrity and reconstruction

Every original file and directory is preserved, including checkpoint copies, SQLite main/WAL/SHM files, raw text, token IDs, model process receipts and all private-home resources. Before/after inventories record SHA256, permissions, ownership, inode/device, link count, mtime/ctime and allocation; atime is excluded because reading may update it. Raw modes are preserved in the archive; PAX supports the actual long paths, and tar UID/GID/mtime are normalized while original metadata stays in the inventories. No original source/run write, chmod, SQLite connection, Rust execution or new model call was used for packaging.

Download every part listed in `manifest.json` and run `python3 verify_and_reassemble.py manifest.json`. The verifier checks each ordered part and the combined SHA, opens the reconstructed tar without extraction, reads every regular member and verifies the two raw run inventories and modes. Each published part is at most 5 MiB. The archive includes exact commands and all current independent reports; no future CI result is needed to verify this snapshot.
