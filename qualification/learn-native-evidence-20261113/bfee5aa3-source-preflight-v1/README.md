# Bfee source preflight and hydration originals

This appendix preserves separate observations for exact source bfee5aa363cb63897c28c8f74fd6b167de5e859b / tree d24d13a0d716036319a6b814dd89b8e913689b00.

* The first scoped-fix attempt failed during its source snapshot, before Rust or tests. Its original result, FileNotFoundError traceback, import/bundle logs, and the separately failed MCP log-read request remain unchanged.
* The read-only source observer found nine absent tracked archive files marked skip-worktree in the reused candidate. The prior fbf source retained the original files. The original observer and all four copied v1 files are preserved byte-for-byte.
* The successor created only those nine missing files from their existing, matching Git blobs. The receipt records the opened empty inode, exact bytes/hash, fsync, unchanged index/flags/config, unchanged earlier evidence, and equal virtual/actual 15,497-file source hash. This is source hydration; it does not establish business recovery. The approximately 21 MB of already tracked archive bytes are not duplicated here.
* The subsequent seven-package `just fix --locked --offline` finished exit 0 in 114.677388904 seconds with identical complete before/after snapshots. It compiled tests but executed none. The preserved result states that scope explicitly.
* The future A-v2 collection command and frozen collector/driver were parsed and checked locally. This appendix does not claim that the collector was uploaded or launched, or that A-v2 tests completed.

The source snapshot failure and successful successor are distinct attempts. Source hydration is not unchanged source relative to the failed v1 materialization. There is no native-test or whole-chain pass in this appendix. The older evidence branch history remains intact.

`manifest.json` identifies every original member and its complete SHA-256. Every tar member was read back and compared with the original bytes, and source files were then rechecked without modification. `verification.json` records the narrow cross-checks.
