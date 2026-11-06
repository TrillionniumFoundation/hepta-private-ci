# Original r8–r8d closed checkpoint

The original archive contains 82 changed source files for tree 6d88ca9c8964669a408d8549efaeff7b94d68674, 27 closed evidence files, and its manifest (110 regular relative files in total). The original receipts, complete logs, resource records and failed process-observation attempt are preserved verbatim.

Root independently verified the archive bytes, every extracted archive member, all 82 source SHA256 and Git blob IDs, then reconstructed the exact Git tree from framework base tree ce997fd958b8073d99b1e5bc302b7a0188fb4c3b. See [root-source-roundtrip.json](root-source-roundtrip.json) and [MANIFEST.json](MANIFEST.json). This verifies source identity and transfer integrity; it does not convert failed tests into passed tests.

The companion directories expose original receipts and separately compressed complete logs for direct review. Some files therefore deliberately occur both inside the original archive and as reviewable attachments. Original relative receipt paths are retained rather than rewritten.

The original r8d process sampler did not capture the test process descendants because it followed only the thread-group main thread. Its empty observations, exact executed harness and explicit limitation remain in the archive and the r8d directory. They provide no CPU or I/O attribution. The original 60-second watchdog and debug-limited source result remain separate from subsequent CI-aligned debug=0 validation.
