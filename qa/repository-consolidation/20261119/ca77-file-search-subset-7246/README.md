# Qualified file-search subset

The original ca77 file-search change keeps the matcher timer active while nucleo reports ongoing work. It preserves the existing query, cancellation, directory, symlink and ignore behavior.

The old implementation, with only the original new regression added, compiled and failed the intended runtime assertion in both attempts configured by the existing nextest profile. The exact incoming candidate then passed all 17 library tests with no skips. Strict Clippy, scoped fix and final pinned format passed; source and Cargo.lock stayed byte-identical. The original Cargo workspace manifest still emits three unused dependency warnings, which are retained in the full logs.

This is a single source subset. The original ca77 tip is not attached as an ancestor and its remaining changes are still pending review.

## Complete records

Read native-results.json for exact commands, counts, toolchains and limits. source-resolution.json pins the original before and candidate bytes. manifest.json lists every complete original member and each independent gzip wrapper. The frozen source review files inside the archive describe their earlier pre-execution state; native-results.json records the later completed qualification.

To inspect the archive, decompress part files in manifest order, concatenate the resulting raw TAR slices, and open the reconstructed TAR. Verify all wrapper, slice, TAR and member hashes from manifest.json. Every raw slice is at most 384000 bytes and every wrapper uses gzip mtime 0. The archive includes the complete expected failing test output, all succeeding gate output, strict source import and durable job records. No test was repeated during packaging or after final fix and format.
