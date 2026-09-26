
# automation.taskflow release qualification

**Automation store schema: v19.** Repository source composition and external
qualification are separate assertions. The source can prove deterministic
identity, durable intent, bounded recovery and the named Agentd product caller;
it cannot self-issue target-host or independent-acceptance evidence.

## Repository-controlled gates

The focused workflow must pass schema/document drift, the closed privileged caller
inventory, Rust formatting, compile, strict clippy, package tests, migration
convergence, structural qualification, Agentd product-effect tests and an exact-SHA
command receipt. A failed or skipped required command is not a release receipt.

## External evidence still required

* selected-host Agentd/App Server execution and restart receipts;
* an independently provisioned final-use signer/verifying key and monotonic
  revocation frontier;
* an attested concrete provider plus trusted terminal/status lookup;
* authentic current IANA tzdb provenance and refresh policy;
* DST gap/overlap, multi-scheduler race, restore, saturation and backlog tests on
  the selected host;
* an independent principal's acceptance signature followed by explicit activation,
  promotion and release decisions.

Until all of those artifacts are bound to one immutable source SHA and target
profile, `deploymentQualificationComplete`, `independentAcceptance`, `activation`,
`promotion` and `release` remain false. Fixtures, localhost mocks, source hashes
and an administrator's own signature cannot substitute for those classes.
