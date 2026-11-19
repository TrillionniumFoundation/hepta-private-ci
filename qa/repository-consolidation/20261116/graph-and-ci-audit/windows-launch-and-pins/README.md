# Windows launch environment and source-pin repair

## Exact source and status

This proposal is based on integration head 60658ec54cf7f857197733fecf455ba44fecd3d4. It changes three source files. Native Windows verification of the changes is pending.

The original AppContainer and LPAC cases both failed at CreateProcessW with error 203 before either child was created. The original unconfined Medium- and Low-integrity NULL-DACL write controls and owned cleanup completed. Those results establish a launch failure, without establishing an isolation outcome.

## Proposed changes

The launch adapter adds LOCALAPPDATA to its explicit environment after requiring a non-empty absolute path without a null character. The six names remain sorted. The other environment values, executable, command, working directory, capabilities, process flags, cleanup, and 5-second child limit remain unchanged. The workflow retains exact source validation and receives the adapter's new SHA-256.

The ACL validator had three stale exact source records. Their reviewed source deltas are the separately locked SHA-256 implementation's optimization and explicit Windows test imports. Updating those records makes all 37 source identities match this head; no comparison or lock validation is weakened. The Cargo record must be synchronized again if the final reviewed source changes.

The Federation workflow adds a Windows-only long-path setting before checkout. Its two platforms, source binding, permissions, 60-minute budget, exact regression command, and assertion that one test ran remain unchanged.

## Completed checks

The repository's scoped Ruff formatter, scoped Ruff checks, the two YAML Prettier checks, and Codespell for the three changed source files passed. Input bytes remained unchanged.

A Linux boundary harness executes the complete actual launch method. Fourteen candidate cases passed, including the explicit environment, both attribute variants, invalid profile variables, and propagation of a failed creation call with attribute cleanup. Both old-source positive cases exposed the omitted variable. This harness substitutes the Windows API boundary and path implementation. It does not qualify Windows ABI behavior, child creation, tokens, permissions, or isolation.

The complete probe implementation, positive assertions, NULL-DACL observations, and original four production-positive tests are preserved. The existing native job must run against the reviewed final PR head with its original budgets. No job was dispatched, retried, or cancelled for this proposal.

## Evidence and recovery

proof.tar.gz is one complete deterministic gzip stream containing the source preimages, proposed bytes, complete diffs, source-history bridge, original native failure logs and downloaded artifacts, actual validation commands, raw output, and validation controls. proof-manifest.json records every member's original source path, length, SHA-256, and Git blob identity.

Decompress the gzip file and read the tar members in an empty owned directory. All members are regular files with relative paths. Verify every recovered member against the manifest before using it. The publication builder also compared every archived byte with its original source file; it did not merely compare two generated summaries.

review.json inside the archive distinguishes official API contracts, the external empirical lead, the current failure, and the unverified causal hypothesis. The full source plan is inside the archive. These are source-level and scoped validation receipts, not whole-repository qualification.
