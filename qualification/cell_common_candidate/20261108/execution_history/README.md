# Source-bound execution history

This is a bounded, lossless checkpoint of engineering evidence. It preserves
the selected original archives, including failures and preparation errors.
It does not certify complete history, complete cost, production authority,
ordinary daemon closure, or any S0–S5 advancement.

## Source identities

| Source | Observed engineering result in these packets | Limit |
| --- | --- | --- |
| `6fd7471bce6102de857c0c7f9da5d5e641b719f7` | 126 independent Python fixtures passed; full caller scan failed. The native run retained an ACT1 timeout. | These failures remain part of the original history. |
| `86ac7796345ec0a885bb212e5174ba85bb16485e` | 127 Python fixtures and full caller scan passed. | The full scan exceeded the original CI budget. UI preparation used a separately recorded dirty patch. |
| `09f543c732e383a62f9339e84b69b373992d6e07` | 130 Python fixtures and the full caller scan passed. The scan completed in 371.628 seconds under the original 600-second cap. The scoped native chain executed 700 core-family cases, 729 agentd cases, and one original HostCAS case successfully. | This is not a complete workspace or ordinary-daemon qualification. Original failed native preparation is preserved. |

The v3 source tree is `9be76894a2984d28e1780a7ff7499c79f506b09a`.
Its 700-case native scope is exactly `codex-hepta-contracts`,
`codex-hepta-neuron`, `codex-hepta-automation`, and
`codex-hepta-bellman-operator`; it is not the `codex-core` workspace suite.
Ignored and filtered cases remain separately recorded in the original receipts.

The SDK UI packet contains the actual seven-case source-head and base-merge
executions. The source-head tested commit is the v3 commit above; the explicit
base merge tested `e422c96f016da757a87134f33923633721702796`, with the same tree.
It does not contain the subsequent full browser/pixel archive.

All three source-bound Python packets retain the unchanged research result
hash `c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4`.
S0, S1, S2, S3, S4 and S5 remain **HOLD**.

## Verification and reconstruction

Run from any directory:

```sh
python3 qualification/cell_common_candidate/20261108/execution_history/verify_packets.py
```

To reconstruct the original archives into new files, add
`--reconstruct-dir /absolute/path/to/output`. Existing output files are never
overwritten. The verifier does not extract or execute archive members.

Each original compressed archive is split into ordered chunks of at most
490,000 bytes. Packet manifests bind the chunk order, offsets, sizes and hashes,
the exact original archive hash, and every original file member. Reconstruction
and member verification were completed before publication. The original
inventory and publication pattern review are retained separately.

## Scope and costs

Some packets overlap earlier history. Packet member counts, test counts and
wall times must not be added across repetitions, nested wrappers or source
versions. A passed command is not necessarily a test execution.

The classification retains four log references with only path linkage and
60 unknown log paths as host-only observations. They are not admitted as
hash-bound raw evidence. Large native executables are represented by their
retained host paths and content hashes; the full executable set is not packaged
here. The helper executable explicitly listed inside the native archive is
included as original bytes.

Physical, CPU, learning and complete history costs remain unknown. Original
wall intervals are preserved as wall intervals. No aggregate cost is inferred
from them. Evidence publication uses a separate Git branch and does not change
the source commit tested by an original receipt. The publication commit is
recorded in an external Git readback receipt, avoiding a self-referential
manifest hash.
