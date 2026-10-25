# Complete original workspace execution evidence

This is a later, additive environment receipt for Hepta PR #3398 at `16418ddc3416a38a122b883cee46e2d3583cbd41` (tree `43fde98e9ea789b81b941e48bb65300c76c4292c`). It preserves the earlier partial-checkout and offline failures as history. Those are no longer the current environment diagnosis.

## What actually completed

- All 9,111 original Git blobs, including file modes, were materialized and matched the exact pinned tree: 104,204,373 source bytes. The original Cargo.lock remains SHA-256 `83651f11dea7f58dc96f3d119c120ab2bd8019e418979ab091ef49de7cceb9e8`. No workspace members or dependencies were removed or changed.
- Approved network access worked. The original locked Agentd normal/build/dev dependency graph resolved successfully, and required dependencies were downloaded into this task’s private Cargo cache. The earlier whole-workspace missing-cache count is not a count of the target package’s unresolved dependencies.
- The actual repository `just test` wrapper was invoked with the original `dev-small` profile, one build job, one test thread, `--locked`, `-p codex-hepta-agentd --lib`, and the 12-test `production_composition::` filter. Compilation progressed through the original aws-auth and other Codex packages, reaching app-server-protocol.

## Why there is still no original Agentd test pass

Five exact recorded attempts cover initial execution and four resumptions. They stopped for a measured cache budget, then the original openssl-sys build’s missing pkg-config, then memory or shared-memory storage limits. The OpenSSL problem was resolved using the actual installed system headers/libraries through the crate’s supported OPENSSL_INCLUDE_DIR/OPENSSL_LIB_DIR variables. No source shim, dependency pin change, fake executable, or reduced test was introduced.

The final attempt stopped on 2026-10-23 at 07:08:56 UTC with 2,991,942,294 apparent target bytes and 267,071,488 free shared-memory bytes, below the retained 256 MiB floor. It did not reach the test binary. Therefore the 7 factory tests, 5 Notes tests, and the original-package issuer/worker tests remain unexecuted by these receipts. The separately published isolated 7-test and 5-test harness results do not substitute for this gate.

## Serial reuse for the original memory package

A separate original locked/offline cargo tree for codex-hepta-memory resolved 533 package names. Only this task’s generated artifacts for ten packages outside that graph were removed, including 15 unfinished app-server-protocol files with no successful fingerprint. Starlark is inside the actual memory graph and was preserved. The cleanup receipt lists every removed path, byte count and SHA-256; it freed 466,351,083 apparent bytes. Original source, lock and dependency cache were preserved. Agentd needs those removed packages rebuilt before its tests can run.

Any later Objective sender candidate overlay is a distinct recorded source identity. It cannot be reported as execution of the unchanged #3398 head. This bundle predates that overlay and contains no memory test result.

`owner-complete-workspace-execution.json` indexes the unmodified full execution bundle in ordered `owner-workspace-raw/part-*.txt` files. The index records every part's byte count and SHA-256, and the complete bundle SHA-256 `7d7e1b5b3b631082216cf353f1e75532fb5aa3c49d7cfee1514f1ad9dc00eb69`. Concatenating the parts in indexed order reconstructs the exact 470,289-byte original JSON, including raw command outputs, tool identities, resource observations, source materialization record, dependency graph and cleanup manifest. The readable index and this addendum are summaries, not substituted execution records. The exact Git tree identity makes the original source reproducible without bundling another repository.
