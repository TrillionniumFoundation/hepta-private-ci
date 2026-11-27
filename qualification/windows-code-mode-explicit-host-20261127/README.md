# Explicit process-host fixture selection

The original Windows run 46074342806 (job 140758443993, source d477785b832dbd1735a7a7f7b36b7d5c1ed6ae38) naturally failed. The complete log and artifact are retained here. CLI passed in 5.3 seconds and exec-server in 14.0 seconds; core failed 6 of 21 attempts. The existing no-retry/no-FLAKY policy correctly rejected this result.

The original disabled_process_host_with_fallback_disabled_attempts_the_host case explicitly supplies a missing host executable and disables the host feature and fallback. TestCodexBuilder discarded every explicit override whenever that feature was disabled. Once the real host was supplied to the test bundle, the default provider therefore ran the script and reached its original unreachable statement.

This change preserves explicit test inputs independently of the feature flag. Automatic cargo-bin discovery still requires CodeModeHost. Production providers, the original case, all assertions, all budgets, and the three-target Windows workflow are unchanged. No additional test retry is introduced.

The original failure also contains the independent subagent-stop missing-hook-entry and inherited-environment thread-limit failures; these remain separate open items with the lifecycle owner. This source change does not declare the whole target qualified.

The real just fmt command completed with exit 0 in 0.3424893750343472 seconds. The next Windows run must use the new commit and run the same three complete targets.
