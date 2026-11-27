# Lossless compressed evidence storage

This storage projection preserves nine original compressed archive streams and all 48 original fragments from commit c0e525fd94e6eea2957bd1a12764627b86dd71ec. It changes the physical carrier representation only. It grants no execution, security, or scientific qualification.

The original Codespell 2.4.3 content detector read five interior Matrix fragments as text. Giving those same bytes a gzip filename still produced the same 39 spelling findings on the controlled part004 comparison. Each new physical carrier is therefore an actual, independent gzip member. The original compressed stream is split into at most 480000 decoded bytes per carrier; every stored carrier remains at most 500000 bytes. Neither the spelling configuration nor the source-custody exclusions change.

## Verify and restore

Run from the repository root to verify every carrier and all original identities without writing output:

    python3 qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/compressed-evidence-storage-v1/restore_compressed_evidence.py --repository-root . --verify-only

To restore, choose a destination that does not exist:

    python3 qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/compressed-evidence-storage-v1/restore_compressed_evidence.py --repository-root . --destination /tmp/hepta-original-evidence

The destination mirrors repository-relative paths. It contains every original logical fragment and each joined original .tar.gz stream. Decode each physical carrier once before concatenation; directly concatenating the new carrier files does not produce the original archive bytes.

The storage index binds carrier order, compressed and decoded lengths, SHA256 values, original stream hashes, and the original fragment offsets and Git blob identities. The restorer rejects missing or extra carriers, malformed paths, symbolic links, duplicate records, bad hashes, truncated streams, trailing gzip members, and size violations. It validates all bytes before creating a new output directory and never extracts tar members. Path checks reject static symbolic links; the command does not bind directories with file descriptors against concurrent filesystem replacement.

## Historical metadata

All pre-existing compressed manifests and receipts remain unchanged. Their fragment names describe the recovered logical files. The Agentd and Intelligence active indexes point to the storage map for those files; their original identities and all qualification statements remain unchanged. The original five active index and readme preimages are preserved in previous-active-metadata.tar.gz.

Two newly retained historical Cell xz fragments keep their original physical paths and bytes. They are outside this representation change. The complete changed-file spelling validation includes those files and all new physical carriers.
