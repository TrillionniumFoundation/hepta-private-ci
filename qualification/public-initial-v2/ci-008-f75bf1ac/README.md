# Actual public V2 observations: source f75bf1ac

Source: `f75bf1ac902ed73905e4daa49f9396df028a4254`, tree
`a8052cd850dcbe6bb6dec4e434bae051cecc7b4c`.
The [original run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40492138476)
and job `122148432828` ended in **failure**. These records are evidence for that
source only; later lifecycle repairs cannot change this run's outcome.

## Observed execution

The three original Rust packages passed 519 tests, with zero failures and 24
skips. A fresh CPython 3.12.3 environment installed the 31 hash-locked wheels,
including Torch 2.9.1+cpu, and rebuilt the V2 material from the seven pinned
public files. The ordinary context test performed three distinct neural forwards
through the original runtime and refused a subsequent withdrawn selection.

The original three-round loop opened its first ordinary incarnation and completed
one real five-arm training/evaluation round. That round held the original parent
because the candidate did not beat the strongest control. The next ordinary
incarnation failed with `RuntimeOpen(StateLocked)`: a previous App Server task
still retained the prompt runtime owner. The loop therefore completed **zero**
train/reopen/readback rounds. Its initial CURRENT receipt remained unchanged.
The skipped lint and failed required-outcome gate are preserved.

The separate six-arm diagnostic completed three real candidate descendants.
Their cumulative post-genesis schedules were 10/20/30 steps, 526/1052/1578 input
tokens and 40/80/120 supervised tokens. In each round, candidate, fresh LoRA and
fresh full tuning scored 1/2 on both calibration and evaluation; original
incumbent, unmodified backbone and random LoRA scored zero. These are 20 public
tasks: 12 training, four calibration and four evaluation. The candidates show
no gain over the best evaluated control. Later candidate rounds also retain
`CumulativeBudgetMismatch` because the original fresh controls restart at ten
steps each time. An independent later controls campaign must close that separate
comparison gap using actual inherited control weights.

Candidate ordinals 2/3/4 are unadmitted diagnostic material. There were **zero
installed children**, zero product qualification receipts and no evidence of
three installed upgrades. Linux test owners and issuers do not establish public
enrollment, independent future-task quality, or post-quantum identities.

## Exact original archive retention

`manifest.json`, `records.recipe.json.gz` and the 15 `records-*.pack` files
reconstruct the **identical 114,661,707-byte records ZIP** with SHA-256
`a6674acfd78bc4172eb0cb2dbd7e39e1bf6506e50fbca30b04b6db19c7f6c276`.
The ZIP was not decompressed and recompressed for retention. Its local headers,
raw compressed payloads, descriptors and central directory were divided in
source order into regions of at most 256 KiB. Duplicate regions were compared
byte for byte before sharing one stored chunk. The 23,181 ordered segments use
59,814,881 unique bytes; the compressed recipe occupies 842,755 bytes. Every
chunk and each pack has its own SHA-256 pin, and every pack is at most 4 MiB.

With Python 3.11 or later, restore to a new output path:

```sh
python3 restore_records.py --output /tmp/hepta-ci-008-records.zip
```

The restorer verifies all pack hashes and extents, every reconstructed segment,
the complete original ZIP hash, the exact original member set, the source/index
binding, and all 11,464 non-index retained records against the original index.
It uses exclusive output creation and does not execute or extract ZIP contents.
`reconstruction-verification.json` records the actual local reassembly by this
separate program and its complete record verification. `observations.json` retains the
acceptance scopes separately. The full API-decoded job log is also preserved as
gzip; the original wrapper-log bytes remain inside the original ZIP.

The separately uploaded **2,175,707,854-byte safetensors checkpoint ZIP** is not
included here and was not downloaded locally. Its GitHub artifact ID, complete
ZIP digest and all 29 checkpoint index entries are retained. Ordinary initial
payload `.bin` bytes already present in the records ZIP remain untouched. The
separate cumulative-controls runner must verify the full checkpoint ZIP and each
consumed tensor file before training; an API digest alone is not local byte
verification. The original GitHub artifacts expire on 2026-11-10. This committed
record pack preserves the records beyond that retention window, and does not
establish permanent decentralized storage for the model weights.
