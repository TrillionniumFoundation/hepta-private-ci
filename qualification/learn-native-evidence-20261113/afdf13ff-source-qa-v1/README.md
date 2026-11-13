# Exact afdf standard source QA: 926 tests completed

The unchanged standard command `python3 -m unittest discover -s qa/b4-no-bypass -p 'test_*.py' -v` completed exit 0 with **926 tests in 218.235 seconds, OK** on afdf13ffc1757c0dfa5d3f6922bde2d746251df7 / tree 7eb8f9f742ce2a28327b6d7aae0b2f0f8cd7ebf4.

The gate ran 02:02:19.350943–02:06:00.621714 UTC (221.270096366 seconds including launcher bookkeeping). Complete physical snapshots before and after were identical: 15,500 files / 234,446,647 bytes / SHA-256 10d16cdd1f455bb0ea756b72156658f33e6a34f1e6f15ccc88c74e4aade5191d. The only repository difference from 5e is the actual caller expectation in one QA file. Source, scanner, tests, command, environment, budgets and test grouping were not altered during execution.

The separately reviewed launcher added only a read-only sampler in the same process namespace and cumulative child rusage. All 221 original JSONL samples are included, with one PID/start and no observation errors. Maximum sampled RSS was 674,780 KiB; final rusage reports maxrss 674,016 KiB. Both original values are preserved separately. They do not establish why older bfee and 5e processes exited -9.

The complete authoritative caller CLI was actually executed on 5e2426ad, where it passed 6,892 Rust files / 1,113 boundaries / 1,113 inventory / 878 protected entries. It was not rerun on afdf. The sole changed QA file is neither a scanner/Rust/CALLERS file nor a declared protected or definition input; the comparison receipt is included. This appendix explicitly records full_caller_executed=false for afdf and does not manufacture a later CLI receipt.

Earlier signal exits, the already-emitted identity subtest failure, and the successful focused correction remain in prior/separate evidence. This successful complete discovery is not a native or whole-chain result. Whole qualification remains 0/0/0. H preparation/connection failures and original native results have separate scopes.

All raw stdout/stderr, complete result/snapshots, launcher before and after the docstring correction, diff, launch/terminal receipts and full resources.jsonl are retained. Every archived member was compared byte-for-byte and original inputs were rechecked unchanged.
