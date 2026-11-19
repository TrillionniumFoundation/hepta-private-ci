# Windows identity and receipt format evidence

This package preserves the source proposals, original commands, input
manifests, logs and test reports for the recorded Linux run. The original
receipt decoder ran three unchanged regression tests: the canonical cases
passed, and both malformed-tag tests failed. The reviewed repair then passed
all 369 tests in four complete packages. All 13,683 inputs remained unchanged
through the original lock recipes, formatting, repair checks and test gates.

The seven new Windows tests are not executed by Linux. The result does not
qualify native Windows behavior, storage durability, path races or the full
branch history. The prior 357-test source vector remains a separate record.

Every numbered carrier is a complete gzip stream. Decompress them in order,
concatenate the output and verify the archive digest in the carrier manifest.
Extract the content objects, then restore original paths using the originals
manifest. Every original byte was restored and checked. The source index maps
the exact 56 source files; the base source kit and later postimages are retained.
