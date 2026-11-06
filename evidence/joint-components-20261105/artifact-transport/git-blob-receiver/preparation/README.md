# Exact Git blob receiver

This cloud-only receiver consumes one already returned GitHub `fetch_blob`
response through bounded local PTY stdin. It makes no network, Git, desktop,
native, source, workflow, or learning call. It does not update the older paused
`binary_read` downloaders.

The common data root is
`/workspace/scratch/93bfcfe29fc8/actual-archive-git-readback/data`.
That directory is reserved for exactly the 166 final transport files. Receipts,
metadata, decoded parts, local controls, and failure logs must stay outside it.

## One-blob metadata

Freeze one metadata JSON file before launching the receiver. Its schema is in
`metadata.schema.json`. The caller must independently establish the immutable
repository, commit, tree, Git blob ID, transport path, payload byte count and
SHA256 from the actual publication/index. The receiver checks the payload's
Git blob identity; it does not independently authenticate GitHub or infer that
a supplied commit/tree label really contains the blob.

All blobs use `schema: github-blob-readback-metadata-v1`, `repository`,
`immutable_commit`, `immutable_tree`, `transport_path`, `transport_bytes`,
`transport_sha256`, `transport_git_blob_sha`, and the exact `request` object:

```json
{
  "repository_full_name": "TrillionniumFoundation/hepta-private-ci",
  "blob_sha": "ACTUAL_TRANSPORT_GIT_BLOB_SHA"
}
```

The placeholder above is documentation only. Actual metadata must contain
lowercase 40/64-character hexadecimal identities.

| Payload | `kind` | Additional fields | Final data path |
| --- | --- | --- | --- |
| Original part encoded as canonical base64 | `base64-original-part` | `original_bytes`, `original_sha256` | `archives/H1`, `H2`, or `H3` followed by `/parts/<original part.name>.b64` |
| Original export completion JSON | `json-utf8` | None | `archives/<phase>/<phase>-export-completion.json` |
| Actual transport index JSON | `json-utf8` | None | `transport-index.json` |

Each part is at most 4 MiB decoded. Its ASCII payload must have exactly
`4 * ceil(original_bytes / 3)` bytes and characters, standard canonical
base64, and no newline. A plain JSON payload is at most 1 MiB and must decode
to an object. Its original UTF8 bytes are retained without reformatting.
The entire serialized RPC is bounded at 8 MiB. Character count is never
substituted for UTF8 byte count.

## CLI and PTY protocol

```sh
python3 -B /workspace/scratch/93bfcfe29fc8/w1/git-blob-receiver-v1/receive_git_blob.py \
  --metadata /absolute/frozen-metadata.json \
  --expected-metadata-sha256 ACTUAL_METADATA_SHA256 \
  --rpc-bytes ACTUAL_SERIALIZED_RPC_UTF8_BYTES \
  --output /absolute/fresh-receipt-directory \
  --data-root /workspace/scratch/93bfcfe29fc8/actual-archive-git-readback/data \
  --payload-path /workspace/scratch/93bfcfe29fc8/actual-archive-git-readback/data/EXACT_TRANSPORT_PATH
```

1. Keep the complete actual tool result in memory. Serialize it once, retaining
   that exact serialization and its UTF8 byte count. Do not regenerate a tool
   response from its payload or from a summary.
2. Start this command in a private PTY and wait for the literal `READY` line.
   Do not transmit payload bytes before `READY`. An invalid bound or unsafe,
   existing receipt-directory argument can be rejected before stdin is read;
   in that case the caller still owns the returned result and must retain it.
3. Write exactly the declared number of UTF8 bytes, preserving string/codepoint
   boundaries when the transport API accepts text. The receiver switches its
   own PTY to raw mode and reads at most the declared extent.
4. Wait for the actual process terminal. A zero exit plus
   `PASS_ACTUAL_BYTES` and the saved successful receipt are all required.
   An uncertain process result must be reconciled; never start an untracked
   duplicate against the same destination.

The raw RPC is captured and fsynced before metadata, response, payload, or
destination validation. A post-`READY` failure therefore preserves the actual
received bytes. A truncated stream remains a `.partial` capture. Completed
streams remain `rpc-original.raw.json`, including failed/error responses.
Failure publishes `failure.json` with no success receipt. Existing payloads
are never overwritten. A failure during a later write may leave partial
published files; this is not a multi-file atomicity claim and grants no
completion credit.

## Saved output and reconstruction

On success the exact payload goes to the supplied data path. The receipt
directory contains the frozen metadata, declared request, original RPC,
`rpc-prefix.bin`, `rpc-suffix.bin`, successful `receipt.json`, and, for a part,
`actual-part.bin`. Every output is reopened and verified before the receipt
is written last and fsynced.

For base64, reconstruction is the exact prefix plus the saved ASCII payload
plus the exact suffix. For plain JSON, the saved payload is the original UTF8
file, while the RPC contains its JSON string literal. The receipt therefore
records `json-string-literal-ensure-ascii-false` or
`json-string-literal-ensure-ascii-true`; reconstruction uses that exact JSON
string encoding between prefix and suffix. An ambiguous or unsupported raw
representation fails with the full RPC retained.

`receipt.json` uses `lossless-github-blob-readback-receipt-v1`. It records
payload size/SHA256/Git blob ID, raw RPC size/SHA256, prefix/suffix sizes and
hashes, reconstruction codec, exact decoded-part identity where applicable,
metadata hash, declared commit/tree, and independently reopened results.
It explicitly gives no native, archive, source, or missing-process credit.
The full raw RPC is retained locally; a later reviewed evidence pack can use
its exact reconstructible representation without storing a second base64
payload. This receiver deletes no original data.

## Concrete local checks completed

`scoped-controls/report.json` records four PTY controls. The first replays the
already saved, actually returned 5,592,515-byte RPC for a 4 MiB original part,
verifies the new payload destination, and reconstructs the same raw SHA256.
The other three use explicitly labelled local fixtures to check Unicode JSON
string representation, complete raw retention after a wrong expected payload
hash, and complete raw retention plus byte preservation when the destination
already exists. These are output/error controls, not new Git reads or archive
qualification. The fixture commit/tree labels are zeros and carry no actual
Git membership claim. The original saved control RPC was read back unchanged.

Actual H1/H2/H3 Git readback remains pending a successful immutable publication,
its independently reviewed commit/tree/index, and root assignment. The failed
first route and all older pause/progress files remain separate historical
records.
