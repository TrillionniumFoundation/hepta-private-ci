# Original Windows sandbox consumer runfiles

The Bazel manifest exports exact helper executable locations, but the Windows sandbox's existing sibling/resource/PATH lookup cannot see those helper directories from another crate's test executable. The CLI and exec-server integration targets also omitted both helper binaries from their declared test data.

This candidate adds the two declared helpers to those integration targets and adds their already-resolved directories to the Windows Bazel test process PATH. A declared helper missing from disk fails before test execution. No product executable override, sandbox mode, deny-read check, permission mask, test selection, retry count, or per-target timeout changes. The original CLI cloud permission target, full exec-server Windows filesystem target, and full 16-shard core integration target are checked independently on native Windows with uncached test results and explicit rejection of FLAKY/retried output.

The shared verified wrapper chain 922 -> 1cf -> 827 is merged normally, together with the earlier durability candidate. Empty completed transport sidecars accidentally staged with the old evidence directory are removed; all original raw failure/success evidence remains intact. Actual Windows execution is OPEN until the complete original targets finish.
