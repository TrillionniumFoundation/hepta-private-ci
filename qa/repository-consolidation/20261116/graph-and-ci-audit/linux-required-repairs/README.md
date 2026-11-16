# GNU and musl CI repair evidence

This package preserves three reviewed proposals against source tree 287374b63ee68a43d4aab7597eea5c90ea67195c and the original failed jobs at c0e525fd94e6eea2957bd1a12764627b86dd71ec. It does not claim that the new complete CI matrix has passed.

## Changes and validation

| Proposal                           | Evidence                                                                                                                                                                                                                                  | Still pending                                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Bazel workflow, one file           | Four actual Bash target-selection cases; original Prettier and Codespell checks. The app-server targets retain their existing assertions and move to the native Linux step.                                                               | The new hosted Bazel jobs.                                                                                            |
| TUI rendering, two files           | Invalidate the completed prefix when the syntax theme revision changes. The new regression keeps the original tests and snapshots. All 501 TUI Rust source files match the pinned tree; every construction uses the existing constructor. | Complete native TUI tests and original package commands. Two explicit rustfmt checks are not the full formatter gate. |
| Guardian test fixtures, five files | The actual original streaming server and ResponseMock passed 15 tests. The candidate passed all 19 tests, including four real TCP regressions. All six original event bodies, old assertions, and budgets remain.                         | The complete Core consumer test and musl qualification. The 19 support tests are not Core E2E.                        |

Guardian validation retains its first candidate compile failure. The second successful test run had two renamed transitive libraries missing from its initial input inventory. The third run resolved that gap and passed with 494 library and macro artifacts pinned before and after execution. All 311 cached libraries in the prior actual link map are covered. Compiler and test output, exact commands, source copies, complete input lists, and both old and corrected receipts are included.

The original GNU and musl job logs remain complete, including failures unrelated to these proposals. No old failure is replaced by a success claim. Full test binaries and the large verbose linker maps remain in the owned work directory with hashes listed in the manifest; the complete actual input and linked-library inventories are included in this package.

## Recover the original bytes

Every physical part is a complete, independent gzip member. Decode each group's parts in index order and concatenate the decoded bytes. The manifest binds each compressed part, each decoded part, each complete group, and every member of the audit archive.

```sh
python3 restore.py recovered
mkdir recovered/audit
tar -xf recovered/audit.tar -C recovered/audit
```

The restore script checks sizes, order, hashes, gzip termination, safe archive members, and the exact archive member set before creating the new destination. It refuses an existing destination and statically rejects source symlinks. It does not claim directory-descriptor protection against concurrent hostile filesystem replacement.

The restored audit contains the full patches, source preimages and proposed bytes, failed and successful local logs, exact tool invocations, the original formatter and spelling controls, source retention proofs, and dependency manifests. The hosted logs are restored separately. No branch, pull request, or CI run is modified by this package.
