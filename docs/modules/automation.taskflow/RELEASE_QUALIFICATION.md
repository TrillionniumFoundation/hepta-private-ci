# automation.taskflow release qualification

## Repository-controlled gates

- [x] schema v19 code and migrations
- [x] migration convergence tests
- [x] durable V1 occurrence and TaskFlow recovery
- [x] bounded batch scheduling and separate recovery/admission budgets
- [x] formal error disposition and SLO contract
- [x] Agentd Calendar V2 product control
- [x] Agentd external-effect host wired through `ProviderEffectTaskFlowDriver`, final-use authority and the attested HTTP provider adapter
- [x] minimal Neural Circuit runtime vertical slice
- [x] fail-closed cross-host recovery manifest and target-admission fence
- [x] crash-point, deterministic property sweep and same-store multi-scheduler race tests
- [x] workspace-wide Rust formatting is enforced with `cargo fmt --all -- --check`
- [x] PR/main focused workflow and retained exact command receipt
- [ ] exact PR workflow receipt is successful for the final candidate

## Selected-host qualification lane

`.github/workflows/automation-taskflow-selected-host.yml` is the only repository-defined selected-host qualification lane. It requires an immutable candidate SHA, a named target profile, a self-hosted runner carrying the `hepta-automation-selected-host` label, and an expected digest for the host's IANA tzdb tree. It fails closed when the checked-out commit, tzdb digest, source map, format, compilation, strict Clippy or any qualification test differs from the declared inputs.

The lane exercises:

- Calendar V2 DST gap/overlap vectors against the candidate source;
- concurrent scheduler claim fencing;
- crash/reopen preservation of unknown dispatch identity;
- deterministic runtime-policy and Neural Circuit bound sweeps;
- cross-host recovery target admission;
- the Agentd `ProviderEffectTaskFlowDriver` product host and reconciliation tests;
- exact host, SQLite, runner, tzdb, commit and tree identity.

A successful run emits `hepta.automation-taskflow.selected-host-receipt.v1`. That receipt is a qualification candidate, not an independent acceptance signature.

## Evidence that remains external

For an activated deployment, the exact candidate still needs:

- provider endpoint and terminal-observer identity bound to the selected target profile;
- independently provisioned final-use issuer keys and monotonic revocation head;
- protected provider/authority configuration provenance;
- backup/restore and real cross-host checkpoint-transfer evidence;
- capacity measurements at the declared admission and recovery budgets;
- an acceptance signature by a principal distinct from the implementation principal.

## Independent acceptance

The acceptance envelope must bind the exact commit/tree, focused-CI receipt, selected-host receipt, target profile, provider/observer identities, final-use trust roots and revocation frontier. Repository CI, an environment approval, self-authored documentation or the implementation principal's own signature cannot satisfy this gate.

Until that independently signed envelope is attached and verified:

```text
deploymentQualified = false
independentAcceptance = false
activation = false
promotion = false
release = false
```
