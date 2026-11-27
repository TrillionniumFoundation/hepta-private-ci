# Exec authorized-read frozen diagnostic sources

This directory preserves the complete qualification harness and native-only assertion inputs from three ordinary source-frozen branches. Their common production Rust changes are integrated separately; the original commits remain the authoritative full historical source trees.

| Head | Historical variant |
| --- | --- |
| `400a3ce92a455599bb67af8cc2ebbec06384ce3d` | Native macOS ARM v2 |
| `6f0e91e1d2479d73ae28097e930e16c4ed331911` | V3 bounded sequential stderr parser and fully executed census |
| `f808b370af071005fe7c8024e1896197f5c094bb` | Raw-source refreeze and alternate UUID-v8-aware closure classifier |

Each `original` directory contains exact bytes of the source manifest, formatter collector, native driver, branch-specific workflow, and both diagnostic assertion files. The `.original` suffix keeps ordinary repository formatting from silently rewriting frozen input bytes. `MANIFEST.json` maps every carrier to its original path and Git blob. The remaining production source bytes are bound by the retained commit and by all fourteen changed-path hashes in the manifest.

## Common production resolution

The method-scoped JSON-RPC metadata and missing refusal/transport regression cases are ported once. Existing dedicated `-32012` overflow handling, strict fixed-message compatibility, capability refusal, bounded decoding, canonical root fixtures and Unix file-identity coverage remain in place. The production macOS ARM assertion is platform-scoped; the original diagnostic assertions here still fail on an unsupported host, and the original collector rejects the host before executing qualification.

The historical diagnostic scripts require one direct child of the frozen `a32d73f` source and a precise fourteen-path change set. They also verify the full tree/index/raw-byte boundary and demand full native owners. These guards remain unchanged. A historical reproduction uses a disposable detached checkout of the exact original head, the pinned host/toolchain and the original paths; copying these carriers into a consolidated tree does not establish a valid frozen source.

## Evidence and limits

`AUDIT.json` records forty-two verified postimages, the eight independently reconstructed and hash-verified modified parent files, three complete product-tree checks, and 119 successful synthetic Python acceptance/refusal checks. These checks cover full owner log counts, mandatory cases, bounded stderr recovery, malformed or incomplete logs, connected BEP identities, retries/cache/remote-action refusal, host identity, selection overrides, native binary header checks and closure classification. They do not execute Rust or Bazel and do not qualify a native platform.

The variants are preserved separately. V3 refuses all ignored/measured/filtered cases and admits only the exact bounded stderr of two pre-existing sequential process-exit tests. V2 and the refreeze retain their original behavior. The refreeze closure predicate has a reproduced gap for a bare `@foo//:libv8.a` target; it is historical evidence only and is not an active guard. The separate declared pre-overlay product tree and overlay digest were not rederived; the complete product tree and source hashes were verified.

No historical workflow is installed into active `.github/workflows`, and no native macOS ARM, Windows or historical Bazel qualification is claimed by this archival integration.
