# Windows AppContainer mechanism experiment

Native Windows execution is **pending**. This package contains the exact proposed source, review, and completed static checks for an independent AppContainer/LPAC experiment. It does not qualify the production sandbox or replace the original four positive Windows tests.

The source plan adds two Python files and appends one independent job to .github/workflows/ndu-windows-storage-probe.yml. Its preimage is ecf17089f0313e795d8700c98bdfe553b2ea8d11. Removing the two added path selectors and the new job recovers every original workflow byte. Both existing jobs, all production admission checks, and all original test assertions remain unchanged.

The job uses the pull-request head SHA as EXPECTED_HEAD, verifies the actual checkout and two fixed script hashes, and retains stdout, stderr, and invocation JSON after failure. Native observation JSON is retained whenever produced; its absence cannot pass. Checkout credentials are not persisted. The original pinned checkout, Python setup, and artifact-upload actions are retained.

## Completed checks

- Ruff formatter and lint checks passed for both scripts.
- The original Prettier check passed for the workflow. The first README check failed on formatting; that failure is retained, and the corrected README passed.
- The original Codespell 2.4.3 implementation and configuration passed for the three changed source files and README.
- Fault injection executed the actual run_case function in both modes. The v1 token-close error interrupts later cleanup. The v2 case remains failed, retains the original error, and completes the remaining owned fixture/profile/SID cleanup.
- Five actual source-snapshot checks accepted the exact source and rejected a wrong head, malformed head, and each changed script.
- Parsed workflow equality and an inverse byte transformation preserve both original jobs and the existing trigger, concurrency, and permissions.

These checks ran on Linux. They do not measure Windows ACL behavior, child execution, NULL-DACL isolation, Root+Read compatibility, or network routing. The new native child budget is five seconds; all original test budgets are unchanged.

## Files

static-proof.tar.gz is a real deterministic gzip archive. It preserves all v1 and v2 proposal, review, gate, fault-injection, and source-snapshot records as captured, including the original negative outcomes. review.json gives the full member inventory and source identities. Verify its hashes before extracting into a new directory.

Only the coordinating root agent may publish the proposed source or advance repository references. No probe run, reference change, production authorization change, or native pass is claimed by this package.
