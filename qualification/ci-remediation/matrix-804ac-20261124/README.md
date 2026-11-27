# Exact804 Matrix migration and consumer qualification

The normal Linux Matrix workflow completed successfully for source
`804ac018433ff08dfd195e93eed936394baf5053`, tree
`a7c03f0857f64d3644c019113ab9c37ae7e7d644`.
[Run 45458365054](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458365054)
and [job 138673838683](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458365054/job/138673838683)
are the original execution, not a later rerun.

The actual baseline0.18 encrypted store was created and reopened at
`07c8994f2402a58f6b59eb648c801fc40c6e2b96`. Candidate0.19.1 upgraded a copy and
reopened it while retaining the synthetic device identity. A separate copy
rejected the wrong passphrase. The normal consumer suite ran 78 unique tests:
78 passed, zero skipped, with23.544 seconds of test execution. This includes
both SDK raw-byte-budget regressions and the business store's existing tests.

`artifact.zip` is the original23,102-byte public CI artifact14956725268. Its
SHA256 is `31a95009cfc136f35f0bf4801ac14152f891771e72a73014ad7d83220b00af26`.
The receipt contains all12 member hashes and all78 unique case identities.
The original logs retain the preexisting deprecated AsyncFd warning.

This qualifies the exact804 Linux migration and consumer scope. It does not
qualify the Matrix SDK encrypted-cache directory's Windows ACL/VFS policy.
The explicit private VFS used by `hepta-matrix-store` concerns the business
SQLite database; that boundary is separate from the SDK encrypted cache.
Later source changes require their own applicable CI qualification. No model
training or duplicate CI execution was performed to recover these results.

Verify the archived evidence without compiling or running tests:

```sh
python3 qualification/ci-remediation/matrix-804ac-20261124/verify_receipt.py
```
