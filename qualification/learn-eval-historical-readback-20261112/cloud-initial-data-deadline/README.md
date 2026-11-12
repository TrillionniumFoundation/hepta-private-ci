# Initial data and original deadline source qualification

The exact source commit and tree are recorded in `source.json`. This is a new cloud checkout of remote source after the previous transient workspace was lost. No previous test cache is treated as a new execution.

`just fmt --base 9e5fe517a94ca7acb285537648f97b378fbb3752` completed with exit zero. The first formatted deadline scope exposed three stale formatting markers; the first complete source suite exposed seven stale function locations in the inherited historical handoff test after the Source converter extraction. Both original failures are retained. The corrective changes preserve the original checks at their actual formatted function locations.

The final `python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'` executed 260 tests, all passing (48.814 seconds). The separate inventory audit checked all 513 boundary definition and declared caller markers and all 388 protected-file rows, with no errors. `git diff --check` completed with exit zero.

These results are source qualification only. The full actual caller scanner, Rust compilation, native execution and Clippy did not run for this tree. Ordinary Initial main assembly, Root LearningTrust and Ledger wiring are subsequent changes and cannot inherit this source result. No A/B/C or whole-system cold-recovery success is claimed.
