# runtime.codex remediation status and developer handoff

Date: 2026-09-29 (Asia/Tokyo). Canonical candidate branch:
`runtime-codex/closure-20260927`. Pull request: `#1123`.

**Draft source candidate; not production-ready.** This status separates code and
evidence formats from actually observed qualification. Every new commit is a
new candidate and invalidates earlier exact-head conclusions.

## Repository-controlled work now present

### Cross-owner effect-entry correctness

The irreversible boundary is Agentd's exact `RunMarkDispatchedExact` CAS:

- the worker freezes the exact App Server request and obtains independent
  final-use authority;
- the local journal durably prepares the exact dispatch and one-shot pre-effect
  abort proof;
- owner/ingress, context, cancellation, absolute deadline, revocation and
  `VerifiedUseToken::enter` checks finish while Agentd is still
  `ContextAttached`;
- Agentd commits the exact run/revision/dispatch digest as `Dispatched`;
- only the original caller receiving a fresh, non-idempotent ACK receives one
  physical-send permit;
- lost, idempotent, stale or mismatched ACKs are reconcile-only and cannot mint
  a permit;
- the abort proof is destroyed when fence commit may be unknown; Agentd rejects
  abort once `Dispatched`;
- typed non-admission and terminal settlement converge Agentd before local
  capacity release.

This closes the original source-level owner split. It is not evidence until the
exact-head and synthetic-merge lanes pass at the final commit.

### Explicit execution state and lifecycle

The product caller is decomposed around typed attempt stages rather than one
ambient collection of booleans. A bounded native thread guard:

- cleans definitely pre-effect and durably terminal ephemeral threads;
- retains possible-effect history;
- records cleanup attempts, failures/orphans and retained unknown history;
- never lets cleanup failure erase terminal or indeterminate ownership.

The absolute runtime deadline is anchored to a monotonic clock with a sampled
wall-clock projection and bounded backward-drift checks. This is local timing
discipline, not an independently trusted time service.

### Issuer and quarantine security

The final-use port verifies signed exact bindings, epoch/revocation frontier,
nonce, validity and protected Unix transport. Linux configuration additionally
pins expected UID, PID, process start time, executable digest, cgroup digest and
host boot-id digest and resamples the connected process around the exchange.
Deployment still must independently attest these values and key custody.

The signed quarantine protocol binds immutable operation/request/dispatch and
evidence digests, authority epoch, monotonic resolution sequence, nonce and
bounded validity. It distinguishes exact terminal closure, abandonment without
replay and a one-shot distinct replacement operation. The verifier is not a
deployed signer, UI, durable external frontier or provider oracle.

### Closed-world crash and source qualification

The candidate now includes:

- an executable 22-cut crash/recovery model aligned with the Agentd fence;
- deterministic 256-contender, restart, lost-ACK, 10,000 stale-revision and
  10,000 digest-conflict stress tests in the same named crash target;
- dedicated `crash-matrix` and `quarantine-protocol` records in the source
  qualification inventory;
- independent exact-head and deterministic ordered-parent synthetic-merge
  lanes with failure evidence retained;
- canonical V2 source receipts and GitHub provenance attestation on direct
  qualification runs;
- required aggregate fan-in for inference-impacting pull requests.

The repository model proves transition invariants. Real process and target-host
fault injection remain separate gates.

### Target-host and operations contract

The protected manual workflow now requires:

- the same source SHA's passed, attested source-head and synthetic-merge
  receipts;
- 30–200 real-provider canaries, default 50;
- all eight external fault scenarios;
- exact provider audit, journal and harness digests;
- source-bound host identity, issuer custody, anti-rollback, canary/rollback and
  independent-review records;
- a canonical target-host V3 manifest with p50/p95/p99/maximum latency and RSS;
- an explicit claim ceiling keeping independent acceptance, activation,
  promotion and release false.

The documentation set includes an index, quickstart, deployment,
troubleshooting, operations, fault harness and acceptance checklist.

## Evidence actually observed for this final candidate

No complete green native Rust/Clippy/product-E2E receipt, synthetic-merge
receipt, verified GitHub attestation pair or target-host V3 manifest has yet
been observed for the commit created by this remediation update. Historical
runs and source-file presence do not fill that gap.

The target-host evidence verifier's repository unit suite is designed to reject
missing fault scenarios, samples below 30, replay/duplicates, post-fence abort,
owner revision rollback, wrong capacity disposition, source drift, missing
external review and noncanonical/tampered manifests. Those tests must still run
inside the exact candidate workflow before a source qualification claim is
current.

## Repository blockers before source closure

1. Run `runtime.codex exact-head` and `runtime.codex synthetic-merge` on the
   exact final commit and require both receipts to be `passed`.
2. Verify both retained attestation bundles independently; a correctly signed
   failed receipt remains failed.
3. Confirm the required `CI required` aggregate consumed the runtime.codex job
   for the pull request. Repository administration must separately decide
   whether to add the two lane names as direct branch-protection contexts.
4. Resolve any compile, Clippy, test-floor, V8, workflow or synthetic-merge
   failure without weakening the inventory.
5. Keep the pull request Draft if source changes continue or evidence becomes
   stale.

## External work not self-certifiable by this repository

The following remain unexecuted external gates unless current independently
issued evidence is attached to the exact source:

- production issuer and quarantine key custody;
- selected target-host process/socket/filesystem identity;
- trusted time and revocation distribution;
- external anti-rollback restore;
- real provider canaries and eight fault scenarios;
- operational quarantine signer/service and operator UI enforcement;
- statistically meaningful resource profile on the selected host;
- canary and rollback rehearsal;
- security, runtime and operations review;
- independent acceptance, activation, promotion and release.

The repository must not manufacture these records with test keys or relabel a
mock-provider run as real-provider qualification.

## Developer reproduction

From a clean checkout, use the pinned Rust toolchain and repository CI setup:

```bash
python3 -m unittest -v \
  scripts.tests.test_runtime_codex_receipt_v2 \
  scripts.tests.test_runtime_codex_target_host_evidence

cd codex-rs
cargo test --locked -p codex-hepta-codex-adapter -- --test-threads=1
cargo test --locked -p codex-hepta-infer-core -- --test-threads=1
cargo test --locked -p codex-hepta-agent-protocol -- --test-threads=1
cargo test --locked -p codex-hepta-agentd lane_b_runtime --lib -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host \
  --test runtime_codex_crash_matrix -- --test-threads=1
cargo test --locked -p codex-hepta-agentd \
  --test runtime_codex_product_e2e -- --test-threads=1
```

The authoritative command inventory is
`scripts/runtime_codex_receipt_v2.py`. Use receipt `verify-contents` only for
integrity and `verify-bundle` with the downloaded attestation for authenticity.

## Operational stop conditions

Stop new admissions and preserve all stores/history on dispatch mismatch,
unknown fence/rejection/terminal acknowledgement, missing App Server history,
failed journal persistence, issuer process drift, stale/backward time or
revocation frontier, provider duplicate/replay evidence, owner revision
rollback or unresolved capacity exhaustion.

Never recover service by deleting journals, rewinding epochs/sequences,
reusing an operation id, treating an idempotent owner receipt as a send permit,
force-releasing quarantine or manufacturing a terminal receipt.
