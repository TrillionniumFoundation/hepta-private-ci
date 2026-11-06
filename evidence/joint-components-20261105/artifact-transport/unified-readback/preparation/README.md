# Unified actual archive readback

This is a cloud-only preparation. The verifier has not run on H1/H2/H3 Git
payloads. It does not perform network calls, publish data, run a native program,
alter source or CI, or update the old `binary_read` download directories.

This v3 preparation additionally pins the actual frozen transport plan, SHA256
`de5bf769089153d2bfd1fae468cf0af7942da442a9856acc120ee611757e5d5b`.
This is the separately frozen second-attempt plan. The first route failed before
publication; its plan and failure remain separate historical records.
Its original bytes are included unchanged. Repository, ref, all 166 paths, all
162 original part objects, and 893,742,124 encoded bytes must match that plan.
The actual index must also explicitly carry that exact `route_plan_sha256`.
The plan is an immutable preparation record; including it does not grant
publication permission or assert that its Git operation has occurred.

## Required inputs

The separate Git fetch owner must supply the complete actual data tree:

* `transport-index.json`, with independently pinned SHA256 and Git blob ID.
* The original completion bytes at
  `archives/H1|H2|H3/<phase>-export-completion.json`.
* Exactly one canonical, newline-free, standard-base64 UTF8 file per original
  part at `archives/<phase>/parts/<original part.name>.b64`.

The input directory must contain exactly those 166 files: 162 envelopes, three
completions, and the transport index. Keep Git fetch receipts and control files
outside that data directory. The caller must freeze the immutable Git commit,
tree, repository, destination ref, and the original fetch-receipt manifest
before running the verifier. These provenance inputs are retained verbatim and
referenced by hash. The verifier does not itself authenticate GitHub responses
or treat locally supplied commit labels as independent network evidence.

| Original archive | Original parts | Compressed bytes | Complete image entries | Actual members |
| --- | ---: | ---: | ---: | ---: |
| H1 | 32 | 130,746,864 | 4 | 9 |
| H2 | 62 | 256,132,128 | 8 | 14 |
| H3 | 68 | 283,427,280 | 11 | 16 |

Original completion SHA256 values, archive SHA256 values, index SHA256 values,
part layouts, and exact totals are fixed in the code. The combined compressed
archive size is 670,306,272 bytes. Image counts are per original run; they do
not imply 23 globally distinct binaries.

## Verification order

1. Require all old downloader pause markers and `PAUSED`/zero-inflight state.
   Read these files without modifying them.
2. Verify the actual index and each actual completion against their fixed
   identities. Require the original part object, name, extent, and offset for
   every envelope. No resegmentation or missing-part inference is accepted.
3. Hash each actual UTF8 envelope, compute its Git blob ID, decode its canonical
   base64, and compare every resulting byte count and SHA256 to the original
   part. Write decoded parts into a fresh output directory and read them back.
4. Assemble each archive from those actual decoded files. Reopen and hash the
   resulting whole archive. Stream and hash every actual archive member; write
   each member to a fresh extraction tree and independently hash written bytes.
   Bind the original exporter, plan, source map, observations, aliases, native
   outcome, and release proof to their exact embedded bytes.
5. Compare the actual new H1 archive's first 65,536 bytes to the existing real
   H1 `.bin` from the original RPC. Preserve the original RPC, request, observed
   remote version, and all old progress files. No new `binary_read` receipt is
   constructed for the Git route.
6. Call the unchanged H2 `verify_partial_representation` function. It reads
   the full 314,572,800-byte prefix of the actual included first daemon and
   hashes that prefix. The partial remains non-executable evidence and does
   not establish a complete second process.
7. Call the unchanged H3 `verify_complete_image_binding` function. H3's original
   failure and unmatched live PID remain intact; the second daemon generation
   retains the original same-held-file scope.
8. Call the unchanged, reviewed `ce96` consumer using the actual restored H3
   archive and all 68 parts, plus the already downloaded actual H4 child and
   its original part. The consumer verifies both whole archives, every member,
   and all 11 H4 logical image views. It awards no new native or capture credit.
9. Recheck every watched old downloader file. Publish a final completion only
   if all preceding checks succeeded and those files remained unchanged.

The three reused Python files are byte-identical to their previously reviewed
sources. Only their pure validation functions are called; downloader `main`,
`dispatch`, `progress`, version-pin creation, and archive export are not called.
No optional native or utility test runs are added. The current preparation
records static syntax and original input/hash checks only.

## Proposed invocation after actual data and provenance arrive

```sh
python -B verify_archives.py \
  --transport-root /absolute/actual-data-tree \
  --expected-index-sha256 ACTUAL_INDEX_SHA256 \
  --expected-index-git-blob ACTUAL_INDEX_GIT_BLOB \
  --repository EXACT_REPOSITORY \
  --destination-ref EXACT_REF \
  --transport-commit EXACT_COMMIT \
  --transport-tree EXACT_TREE \
  --fetch-receipts-manifest /absolute/original-fetch-receipts-manifest.json \
  --expected-fetch-receipts-sha256 ACTUAL_RECEIPTS_SHA256 \
  --output /absolute/fresh-readback-directory
```

Execution remains pending actual inputs and root review. Use a fresh output
directory; failures can leave partial decoded or extracted output without a
completion marker. No automatic retry, cleanup, original replacement, or new
success credit is implied. This is post-run byte verification and does not
change any native test, campaign, public-service, or release budget.
