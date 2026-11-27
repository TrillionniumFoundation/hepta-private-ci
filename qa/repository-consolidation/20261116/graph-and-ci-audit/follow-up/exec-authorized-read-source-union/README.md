# Authorized read source union evidence

The original Linux package run passed all 528 executed tests.
Three existing Windows cases remain skipped on Linux. No Windows, macOS,
full repository, or branch ancestry qualification is claimed.

All four native gate stages preserved the 7763 native and 8074 total inputs.
The original logs, JUnit results, source proposal, input maps, and cache
cleanup records are preserved in the 166-file archive.

Each physical chunk is an independent gzip file. Decode each chunk in the
order recorded in carrier-manifest.json.gz, concatenate the decoded bytes,
and verify the original archive SHA256 before opening that archive.
The decoded chunks form the original gzip stream, which requires a second
decompression to recover the tar archive.

The frozen manifest.json.gz retains its original names and bytes.
The carrier manifest maps every historical part to an exact offset in the
reconstructed stream and preserves both earlier publication metadata sets.
No source, test, assertion, timeout, skip list, or Codespell rule changed.
