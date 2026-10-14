# Pinned Token ID Stream Bridge V2 — research only

**Admission:** `production_admission=BLOCKED`, `selection_authorized=false`.
This is **not** a new native wire protocol or an authorization/attestation authority.
It is an isolated shadow research extension stacked on #2015, which is stacked on
#1995/#1987/#1964/#1963. No Rust Worker, Q24, artifact, CNS, NDU or selected
model is changed.

## Why the earlier check was insufficient

The tokenizer-only preflight measured untruncated lengths and published an
ordered Token ID digest for 128 original AG News retrospective records, but the
actual `model(**encoded)` call and the independent Reviewer never compared
**the IDs actually forwarded** against that receipt. Unchanged padded shape,
model version and batch width do not imply identical Token ID sequences: changing
an ID can leave length and attention mask unchanged while altering learned
representations and Head evaluation.

This patch adds a versioned *research* preflight V2 receipt, retaining the
original V1 global digest field and adding a separately framed per-Cell digest.
For each of the two isolated Cells, the digest commits to the ordered 64 tuples:

```
(cell_id, index_in_cell, full_question_options_state_sha256,
 unpadded_input_token_ids_in_original_order)
```

All numbers have strict integer semantics. Each row is framed with an eight-byte
big-endian payload length and the hash is SHA-256 domain separated by Cell.
No raw tokens, prompt contents, credentials, learned authorization, or provider
payload are written to the published research receipt.

## Actual Encoder identity

`_tokenize_and_capture` (real path only) now requests special tokens and
attention masks **explicitly**, requires right-contiguous padding, and hashes the
unmasked IDs from the very same `input_ids` tensor passed into the Encoder.
It does not call the tokenizer again to manufacture matching evidence.
Existing standalone/synthetic callers with no Cell lineage remain backward
compatible and non-authorizing.

The full original source ZIP, weights, tokenizer, model revision, capture
length and batch must match a bounded, canonical, create-only preflight V2
receipt. Before real model load, the Producer requires it; after each genuine
Cell forward, the Producer compares its measured ID digest against preflight.
The separately started Reviewer independently checks the exact preflight file
SHA-256 and the Producer's digest and repeats the digest comparison on its
own freshly encoded model input, before claiming NumPy Head equation replay.

**Important:** The same runner producing two matching digests has NOT provided
independent ownership signatures, legitimate use rights, a true prospective
outcome ledger or causal model improvement. A self-reported source/forward
counter remains a claim until a separate trusted owner verifies the actual
physical execution. The original fixed 32 retrospective holdout cases cannot
be relabeled as new future-window samples.

## Tests and limits

Run inside `qualification/neuron-shared-encoder`:

```
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
python -m pytest -q -p no:cacheprovider tests/
```

Local complete research suite: **156 passed** (pretrained weights unavailable
in this isolated container). New adversarial tests require equality under
identical token streams and distinguish altered token IDs *of the same length*,
non-contiguous/false padding, source/dataset/model revision drift, missing or
swapped Cell, forged counts, changed hashes, duplicate/noncanonical JSON,
symlinked receipt files, injected authority fields, malformed publisher bundles,
and synthetic baseline non-promotion.

The original preflight SHA-256 artifact and newly emitted per-Cell SHA-256 fields
are retained only as research evidence, not as a signature or an extension of
production `FinalUse` trust. Exact GitHub Actions results, Model Forward receipts,
CPU/GPU resource cost and independent no-change/NDU acceptance remain blocking.
