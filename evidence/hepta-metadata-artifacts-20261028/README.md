# Metadata-only successor to the ordinary-model prerequisite fix

This is an output-scope change after the original execution. It does not qualify
a model, install a child, replace a control, reduce a quality threshold, relax the
12 GiB host requirement, or change an original training or observation budget.
The explicit earlier denial of checkpoint export is preserved. This successor
does not authorize exporting a tensor through another filename or archive.

## Source and preserved predecessor

The predecessor remains local commit
`894704474237b8771695be88dc115c9a4887fd2b`, tree
`29e5eeda1540df63cafa06380fb93c1da01ea38f`, based on
`bf32538ccb9b52e3e0a8e089983eea7e3940b6a5`.
It was independently observed on draft PR 4144 as remote commit
`9e06290d2a5fc36dcc8f6d25a40a24fd9c200256` with the identical tree.
The old local commit, evidence, patch and bundle have not been rewritten.

The predecessor retained the original 1,840 passing / 35 failing Rust outcomes,
the failed third-round RSS observation, the 14 prerequisite controls, and the
actual local 8 GiB host refusal of the unchanged 12 GiB guard. Those records are
historical outcomes. They are not results of a new complete gate on this tree.

## Export boundary

`scripts/hepta_smollm_metadata_artifact_v1.py` reads the original source-bound
evidence index, selects explicitly named root records and bounded stage paths,
and copies only text evidence whose size and SHA-256 still match that index.
JSON and JSONL are parsed with duplicate-key and payload-key rejection. Non-UTF-8
bytes, NUL bytes, binary patches, symlinks, FIFOs, oversized files, changing
files, hidden paths, path traversal and unsafe output reuse are rejected.
Selection uses held directory descriptors and no-follow opens on Linux, the
platform of the original model workflow. A failed selection removes its own
partial directory and cannot enable the artifact uploader.

The uploader can read only the separate successfully validated metadata
directory. The full model-run directory and separate safetensors uploader are
removed. Unknown files, compressed archives, checkpoint payloads, wrapper
payloads, SQLite stores, issuer state and hidden cache trees are not selected.
The original index remains evidence of producer-recorded hashes, including
omitted paths. An omitted hash is not checkpoint retention, a re-read of that
payload, or independent model-payload replay availability.

The same review found source archives in two automatic companion workflows:

- `hepta-architecture-convergence.yml` now uploads only root JSON command
  records and their bounded log names. Its generated source archive stays local.
- New script paths also trigger the existing `hepta-pon-native-pair.yml`.
  Its uploader now selects root command metadata, logs, identities and source
  hashes; both source archives and nested learning-study payloads stay local.
  The Windows ledger uploader lists its nine exact source/record/log files.

`upload-artifact-inventory.json` inventories every declared upload action in all
82 workflow files: 100 steps after this change. It records triggers, parameters
and reusable-workflow edges. Other release/manual workflows are not dispatched
by this change. The inventory does not certify arbitrary future manual runs or
the contents of unknown historical archives. Automatic blocking-CI command
records, Bazel logs, Fleet outputs and V8 build distributions have no path into
the real-model run directory. Original tests and source-archive creation still
execute; only outbound artifact selection changes.

## Actual checks

`metadata-controls.json` and its complete log record 14 real disposable-file
controls, all passing. They cover record retention, omitted-payload behavior,
hash mutation, symlinks at both levels, FIFO input, binary disguised text,
binary patches, tensor-bearing JSON, duplicate keys, wrong source or attempted
qualification, unsafe output reuse, byte bounds, and every JSONL event.

`historical-archive-replay-final.json` applies the final exporter to the actual
old 141,723,863-byte records ZIP, SHA-256
`6e948cdd5d5028c62eb1b049144d3a76e5ed0f17c3fb7b370a8072d59d9df2dd`.
It checks the whole ZIP hash, extracts only allowed text inputs, and exports
369 files totaling 34,388,838 bytes. No selected input fails validation. The ZIP
has 11,746 members; the original producer index lists 11,785 paths, of which
11,417 are omitted by this filter. These are different denominators because
the original index includes checkpoint paths absent from this records ZIP.
No training, tensor extraction, checkpoint export or ordinary installation was
performed by the replay. Its temporary selected files were removed afterwards.

`workflow-output-audit.json` compares parsed predecessor and successor workflows.
Every original execution step, condition and budget is identical across all
three changed workflows after removing only the new output-control steps and
normalizing the changed upload fields. No Rust, Cargo or model source changes
are part of this successor.

The first actual `just fmt` attempt failed while the sandbox could not fetch
the locked formatter; that failure is retained. The exact Ruff 0.15.13 wheel
was subsequently acquired with its locked SHA-256, and the real repository
`just fmt` completed. The final formatter receipt records the two source ASTs
before and after formatting; it does not substitute for the prior actual
controls or original CI qualification.

## Remaining model-loop boundary

The original public three-round caller deliberately holds the original CURRENT
when gain is nonpositive. Positive experimental candidates require original
product qualification and are not automatically installed. Descendant
diagnostics likewise report typed installation blockers. A green run of those
callers can show real parent reads, training and evaluation, plus ordinary reads
of unchanged CURRENT; it does not by itself establish a newly trained installed
child. A real installed-child claim still requires the original qualification,
ordinary installation and next-task byte readback receipts for that child.
