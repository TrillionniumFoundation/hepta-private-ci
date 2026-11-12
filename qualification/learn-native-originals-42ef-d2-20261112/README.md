# Original ordinary-A native evidence: 42ef and d2

This archive adds 75 original H files (4,555,510 uncompressed input bytes) after the independently retained post-0520 through 42-compile archive. It preserves the complete original drivers, launch/execution records, scoped compilation output, actual test-binary preparation, fresh JUnit, explicitly excluded prior JUnit and four child process logs.

| Source | Actual scope | Observed result |
| --- | --- | --- |
| `42efbb8d5ed44b2a1019bac5ac34ad0da0243d5d`, tree `2138a6b1b5e1cbf6501fe1af02baf637328b0239` | One exact ordinary-A ignored parent, real UID0, `just test`, retries 0 | 0 passed, 1 failed, 0 skipped; command exit 100; source unchanged |
| `d2a78cd815f94ddae586d5b5261c43bf3fa331e6`, tree `95f1f58be8ca0af4d523a6e9b5161c1d57ad295b` | Scoped `just fix` compilation | Exit 0, source unchanged; no native test execution in this stage |
| Same exact d2 source | One exact ordinary-A ignored parent, real UID0, `just test`, retries 0 | 0 passed, 1 failed, 0 skipped; command exit 100; source unchanged |

The fresh XML files each contain exactly the requested A parent. Duplicate copies and explicitly excluded prior XML are not additional executions or passes. These records do not establish Adopt, evaluated post-B NoUpdate or whole cold-recovery success. Whole-chain counts remain 0 / 0 / 0.

`manifest.json` records each original path, size, SHA-256, Git blob identity and original ownership/mode. Both the original verifier and this lane independently opened the archive and checked all 75 members; the embedded manifest matches the supplied original manifest byte for byte. Pinned executable files are excluded. No H command or Rust test was run by this archival operation.

Archive: 102,100 bytes, SHA-256 `0ef4d9674724e0112c7d0853990091ca2e3406fe1e3b29cdaabc8d3753ef583f`, Git blob `e06f745cd2320d6c04854ddcfb240d5b4ecb991c`.
