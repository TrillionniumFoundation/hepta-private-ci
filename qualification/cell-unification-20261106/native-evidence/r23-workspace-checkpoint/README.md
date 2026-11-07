# r23 default-workspace checkpoint

The original source49 default-workspace gate failed with natural exit code 100. It executed 20,228 unique tests: 20,220 passed, seven failed and one timed out. The original nextest summary reports 130 skipped tests. This group preserves a failed gate and does not grant qualification.

The command was `just test --locked --retries 0`, with all 193 default workspace members. The source tree is `be34ab1afe622ad3b8f030c8c5018f4f54fbc304` at source commit `50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a`.

- `archive/` contains the byte-exact original archive and its untouched 210-entry INDEX. The 188 source files remain inside the archive and are not duplicated in this group.
- `original/` carries all 16 evidence files and six input files. Large UTF-8 files use reversible gzip with mtime zero; `SOURCE-TO-DESTINATION.json` binds the original and stored bytes.
- `root-readback/` contains the root agent's independent reads and result reconstruction.
- `independent-readback/` carries all 20 frozen historical-agent artifacts and their original handoff manifest without alteration, including the independent full-tree and full-log reconstruction.
- `native-export/` separates the successful pure-Python exporter from the failed Rust test gate. Its original controller captures, stdout, stderr and exact exporter scripts are retained. The failure-ID supplement was created after the archive and is labeled separately here.

No tests, source changes, final fixes, formatting or publication occurred while assembling this evidence group. The failure blocks, original assertions, timeouts and skipped-test reporting are preserved.
