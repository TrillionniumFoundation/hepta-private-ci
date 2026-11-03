# Request-local connection reuse preserves authority revalidation

The actual 16-peer truncation test failed with all sixteen peers classified as
deadline/cancelled under the unchanged two-second product budget. Explicitly
closing fixture writer pools did not fix it. The diagnostic run observed:

- Seventeen initial source discoveries completed at 596 ms.
- The sixteen preflight authority opens began at 597–611 ms and completed at
  1,076–1,586 ms.
- Actual transport reads then completed in 208–585 ms each.
- Postflight authority opens began at 1,286–1,894 ms. None completed before the
  global deadline.

The data reads succeeded, but repeated connection setup and verification made
their postflight admission unavailable. Raising the budget or omitting postflight
would change the contract rather than repair this overhead.

The candidate reuses the read-only pool already opened by initial discovery,
only for that product request. `FederatedMemoryReader::rediscover_current` calls
the same store-integrity, foreign-key, owner and schema verification, then
queries all current capability heads again. Both preflight and postflight still
run through `execute_once` and its original stop/deadline checks. No authority
decision, head row, grant revision, or read transaction is cached between phases.
The actual memory read transaction commits before transport returns; subsequent
autocommit reads see newly committed WAL updates.

On Unix, discovery records the canonical main database device/inode, and every
reuse checks that pathname identity before and after verification/query. A
replacement or redirected database path fails closed even if the pool retains
an older open file. This is a request-local path check, not a descriptor-bound
recovery protocol or independent rollback witness. Ordinary WAL writes are not
inferred from main-file mtime. Platforms without the implemented stable file
identity retain the original fresh-open discovery path.

Authority observations now take their completion timestamp after the fresh
queries. The original lease, response and global deadline checks therefore do
not treat time spent validating authority as an earlier observation.

Six new regressions cover fresh revoke/regrant reads on the reused pool, changed
schema rejection, real database pathname replacement, symlink redirection, and
two full `execute_once` paths that revoke or regrant after a real nonempty memory
read. The last two must suppress the already-read evidence during actual
postflight and retain deny-all authority. The existing sixteen-success/one-
truncated-peer assertion remains intact under the original two-second budget.

Apply this production patch only after reversing the temporary
`cell-peer-phase-diagnostic.patch`. It is based on the original production
source, not the instrumented variant. The separate test-only coverage message
and explicit fixture close may remain. No new timing diagnostic belongs in the
production implementation.

Actual compilation and test receipts must establish success. Source review and
these test definitions alone are not a passing qualification. In particular,
preserve the failed baseline, isolated diagnostic runs and unsuccessful fixture
close attempt in the evidence ledger rather than replacing them with the final
test result.

## Actual final qualification

The exact-base v2 patch was applied after reversing the phase diagnostic.
The `federation-pool-reuse-v5` run then passed 19/19 selected tests, including
the unchanged 16-completed/one-truncated peer fixture under its two-second
budget, all six new pool guards, and the actual untrusted-memory/final-use
test with its built Codex App Server configured. Test execution was 34.464 s;
the outer command took 182.673038 s wall and 304.099412 child CPU seconds,
including compilation. These are qualification costs, not request latency.

The first v1 pool patch was rejected atomically on an EOF-context mismatch;
only the exact-base v2 production change was applied. Keep that setup failure,
the original deadline failures and unsuccessful fixture-close attempt in the
ledger. The original broader group was 559 passed and two failed out of 561;
it was not rerun in full. The later scoped 19-test run contains both previously
failing paths and the new freshness regressions. See the
[final qualification result](CELL_QUALIFICATION_RESULT_20261030.md) for the
complete language/maintenance gates and the boundaries of those claims.
