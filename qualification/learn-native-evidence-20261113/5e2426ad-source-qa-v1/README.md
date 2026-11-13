# Exact 5e2426ad source QA: signal exit and an emitted subtest failure

This appendix records the completed source-QA command on 5e2426ad737fc5f8bef5c69e4a49f4b9a0275be4 / tree d9e8346daaa98162d583b7b5c8aad5b49cf960ed. It does not describe native execution.

The complete unittest discovery of all qa/b4-no-bypass/test_*.py ran from 01:45:48.037733 to 01:48:37.949933 UTC (169.911982797 seconds) and returned -9. The complete before/after physical source snapshots were equal: 15,500 tracked files, SHA-256 60df345e7700fc84d422370878e5af9aaf5902a12491be830b946e324992bb6b. No final suite count or final traceback was emitted.

Before termination, stderr did emit one explicit subtest FAIL: OriginalQ24OutcomeControlCallerTests.test_exact_product_callers_and_inventory, identifier q24_outcome_control_original_identity. This failure is retained separately from the signal exit. It must not be summarized as a run without test failures. The frozen CALLERS row includes the actual cell_q24_task_observation_control.rs caller while the old local QA tuple contains only config/state.

The last reported test differs from the earlier bfee -9 run. The complete original tail comparison and both original stderr files are retained. Available read-only resource observations are not evidence of the cause: cgroup memory files and pressure data were unavailable; the recorded child PIDs were not visible in the observer exec's proc view. Neither timeout nor OOM is inferred.

The independent authoritative caller CLI continued sequentially on this exact same frozen source. Its still-growing logs and unfinished result are deliberately excluded here. They will have a separate terminal appendix. No source, checks, budgets, test selection or compiler profile were changed and no native tests were run by this driver.

Every archived member was read back and compared byte-for-byte and original file metadata/bytes were rechecked. Prior evidence history is retained. Whole qualification remains 0/0/0.
