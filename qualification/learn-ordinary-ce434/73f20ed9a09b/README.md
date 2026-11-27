# Exact-source native evidence for LEARN

Source `73f20ed9a09bc5716484f497654640aedcec268d`, tree `00837edc418de10fe93077b4176c03c8ffd940f8`. This evidence-only branch does not change that tested source.

The four affected crates executed 1,305 native tests: all passed, with zero raw-JUnit failures, errors or skips and no retries. The separate canonical alias regression executed 23 tests: all passed. Each original execution record binds identical clean source identities before and after. The fresh raw JUnit and original execution logs are included unchanged and SHA256-bound in manifest.json.

The earlier same-source long-TMPDIR run really executed 1,305 tests with 1,273 passes and 32 failures. Observed failures included Unix socket path-length errors in the qualification setup. Its failed raw execution and JUnit are retained separately. The later success does not overwrite or relabel that failure. The unchanged parent alias run retained 6 passes / 17 failures out of 23.

Windows 32 native cases passed in https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43038208231/job/130582633699 . Full caller proof passed on PR merge commit 6505211aa6eff85db2b50b326bd988ed631ab44c with the same tree: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43038208642/job/130582839876 .

## Acceptance boundary

Complete ordinary positive adoption: unproven (0). Complete ordinary NoUpdate/fallback: unproven (0). True daemon plus Root cold restart for that complete chain: unproven (0). Native component tests, independently signed test fixtures, physical file reopen, other branch results and infrastructure skips do not count as those chains.

This artifact concerns source73 only. Later original-owner integration commits require their own exact-source validation.
