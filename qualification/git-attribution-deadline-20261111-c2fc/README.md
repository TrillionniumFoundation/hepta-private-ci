# Git attribution recovery deadline qualification

This is a narrow test repair based on #5846 at c7633658aef42077f51fa71a1b727b4653ddb76b. The production policy resolution deadline remains five seconds. Unit tests now exercise that same deadline instead of substituting 500 milliseconds.

The existing refresh test waits for the first HTTP request, refreshes authentication, receives a stale response, then requires recovery from a 401 and exactly three requests. Its first response now takes 600 milliseconds, a valid response duration within the existing production budget. It preserves the timeout Result instead of collapsing Elapsed into None, checks the enabled policy and verifies the current authentication generation. The request-count expectation remains intact.

## Recorded runs

- The unchanged c763 baseline passed both crate tests with zero retries.
- With only the strengthened test and the original 500 millisecond test budget, the refresh test failed with Elapsed(()); the unauthorized recovery test passed. This is a constructed counterexample to the shortened test deadline, not a replay proving the cause of the original hosted failure.
- With the existing production five-second budget used in tests, both crate tests passed with zero retries. The refresh test completed in 0.702 seconds.
- just fmt completed successfully. It joined one async move expression onto a single line. The exact executed tree, formatted source tree, hashes and whitespace-only diff are retained. Tests were not rerun after formatting, as required by AGENTS.md. The published head therefore does not claim execution of its exact final bytes.

Raw command output is preserved losslessly in the log.gz files. manifest.json binds their raw and compressed SHA-256 values. The patch files bind the red and green source changes to the base commit. Source and result JSON files are the original records, including the maintenance record showing that byte identity changed during formatting.

## Boundaries

The original hosted scoped job 130130648526 at c763 failed twelve tests. The swallowed timeout Result prevents that historical git-attribution failure from distinguishing Elapsed from a policy returning None. This change does not establish the cause of all hosted failures or resolve the Matrix, RMCP and core large-output failures. No whole-suite or hosted-CI success is claimed. These are engineering fixture tests, with zero new independent real confirmations and no production adoption, learning benefit or RSI claim. Measured command wall times are retained; CPU and complete research cost remain unknown.
