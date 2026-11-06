# Original C2 native receipts

The complete original export is [native-receipts.tar.xz](native-receipts.tar.xz): 759,728 bytes, SHA-256 `cf4616a52648b6d7ce181fb9233ed4f71cd36746a03309a93515c08e5009be25`.

It contains all 87 original files, totaling 14,096,349 uncompressed bytes. This includes the complete 11,191,235-byte native stdout, both locked dependency-graph stdout files, all 70 command stdout/stderr records, 37 actual empty log files, and the 707,216-byte retained ELF. Small files are also provided individually for review. Their paths and bytes match the archive; larger originals are retained inside the archive.

From an isolated copy of this directory, extract the archive and verify the supplied original checksums:

```sh
tar -xJf native-receipts.tar.xz
sha256sum -c SHA256SUMS
```

Root independently compared every archive member to the actual exported file, then checked the file's recorded size and SHA-256. See [root-review.json](root-review.json) and [export-index.json](export-index.json). The archive contains only relative regular-file paths; extraction does not require any remote service or compilation.

The source is Chain `03521b2f32346a49cccde8ff72e8c7b886b31222`, tree `e0235248ecae2a67717c8b9ff2e3f25774ba63d7`. Original prepare, collector and reader phases passed. Original checks remain failed because the applicability command timed out at 300 seconds. No timeout, failure or empty log was replaced or omitted.

The retained binary's SHA-256 is `39a2d4f3e2cc62b799a8871846d3303537b67badc67f662dd5dadd9601e7b959`. It is the image retained by the original collector, with the same recorded hash before and after execution. It was not rebuilt for this export.

These are local source-bound finite observations. They do not qualify globally cheapest legal work, the original hosted public-service gate, independent administrators or a WAN deployment.
