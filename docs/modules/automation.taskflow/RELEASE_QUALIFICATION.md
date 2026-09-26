# automation.taskflow release qualification

## Repository-controlled gates

- [x] schema v19 code and migrations
- [x] migration convergence tests
- [x] durable V1 occurrence and TaskFlow recovery
- [x] bounded batch scheduling and separate recovery/admission budgets
- [x] formal error disposition and SLO contract
- [x] Agentd Calendar V2 product control
- [x] Agentd external-effect host wired to final-use authority and provider adapter
- [x] minimal Neural Circuit activation adapter
- [x] fail-closed cross-host recovery manifest
- [x] PR/main focused workflow and retained command receipt
- [ ] exact PR workflow receipt is successful for the final candidate

## Selected-host evidence

The selected deployment must provide, for the exact candidate:

- operating system, architecture, filesystem and SQLite versions;
- current authenticated IANA tzdb source/release and digest;
- DST gap and overlap vectors for deployed zones;
- concurrent scheduler/fencing race tests;
- crash/restart and unknown-provider reconciliation tests;
- backup/restore and cross-host manifest verification;
- capacity results at the declared admission/recovery budgets;
- provider and terminal-observer identity;
- final-use issuer keys, revocation head and protected configuration provenance.

## Independent acceptance

Acceptance must be signed by a principal distinct from the implementation
principal and bind the exact commit/tree, workflow receipts, host profile and
provider/authority configuration. Self-authored documentation and repository CI
cannot claim this gate. Until such evidence is attached:

```text
deploymentQualified = false
independentAcceptance = false
activation = false
promotion = false
release = false
```
