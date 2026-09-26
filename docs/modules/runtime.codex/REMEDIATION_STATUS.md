# runtime.codex remediation status and developer handoff

Date: 2026-09-27 (Asia/Tokyo). Branch: `codex/runtime-codex-consolidated-20260927`.

**Draft source candidate, not production-ready.** This status supplements the technical guide and supersedes any interpretation that the mere presence of a workflow, an operation mapping, or a test proves qualification. Main and the earlier remediation branches remain unchanged.

## Actual changes in this candidate

The candidate builds on the existing `9bda7cd52beb86dc6397254c77e4e551a51c164d` remediation branch and incorporates the earlier abort work into actual Rust source rather than leaving it as an unapplied conversion script.

- Native journal: persist an exact owner dispatch binding, a two-stage pre-effect abort intent/acknowledgement, and a local-only loser disposition. Reopening a pending abort reconciles it instead of sending another turn. New Started/Observe/Reject transitions cannot silently bypass a pending abort. Legacy journal records retain compatibility defaults.
- Agentd: introduce exact dispatch and pre-effect abort RPCs, checking run identity, dispatch digest, expected revision, and reason. Idempotent abort retries require the original abort revision; an unrelated ordinary cancellation is not an abort acknowledgement.
- Product caller: move execution orchestration into `native_execution.rs`, route final-check failures through one compensation path, and connect non-cloneable attempt stages to the caller. This is a partial typestate decomposition, not a claim that every state is statically impossible to misuse.
- Terminal durability: persist observed terminal facts before unsubscribing the ephemeral thread. A failed journal write must not remove the remaining recovery history.
- Lifecycle: a bounded thread guard cleans up definitely pre-effect or durably terminal threads. Possible effects preserve history. Counters distinguish cleanup attempts, cleanup failures/orphans, and retained unknown history. A durable orphan reaper is not implemented.
- Deadline: anchor the request to a monotonic clock and a wall-clock sample, refuse excessive backwards wall-clock drift, and cap later budgets by the original deadline. This is local clock discipline, not an independently trusted time service.
- Tests: replace a brittle source-string assertion, pass an explicit Codex executable into the cognitive test host, add deadline and state tests, and add actual child-process kill/reopen tests around eight native-journal cuts.
- Evidence tooling: V2 requires the complete ten-command inventory, exact command/test floor/candidate/lane identity, unchanged worktree, bounded logs and matching hashes. Missing, skipped, cancelled, timed-out, malformed or zero-test evidence fails. Integrity-only verification explicitly does not claim signature authenticity. External acceptance and deployment claims cannot be enabled with CLI flags.
- CI: separate exact-head and deterministic ordered-parent merge jobs with fail-fast disabled; retain failure evidence; isolate OIDC/attestation permissions from candidate-code execution. Workflow presence is not proof of branch-protection enforcement or signed receipt production.

## Verification actually observed

The 21 Python verifier tests passed both locally and on the hosted Rust 1.95.0 formatting runner. Hosted `cargo fmt` and `git diff --check` completed successfully for the assembled source. Earlier assembly failures were publication/infrastructure failures and are retained in Actions; they must not be represented as native Rust test failures or passes.

At the time this handoff was written, no successful complete native Rust test/Clippy/product-E2E receipt, synthetic-merge receipt, or verified attestation bundle for this final candidate had been collected. Read the exact candidate's Actions results rather than assuming a later run passed. A subsequent documentation or code commit is a new candidate.

## Blocking correctness review still required

### Server-owned effect-entry fence

The worker owns an unforgeable live pre-effect abort token, but the new Agentd abort RPC transports serializable run/revision/digest/reason fields. Those fields alone cannot prove to Agentd that no physical send has occurred. Before merge/activation, add a server-owned effect-entry fence, enforced at the same owner that controls the effect, or an equivalent authenticated one-entry protocol. Once the fence may have been committed, abort must be impossible and a lost fence acknowledgement must remain reconcile-only. Add adversarial tests for abort-after-send, fence/abort races, duplicate workers and lost fence acknowledgement. **The current cross-owner P0 is not closed.**

### Owner lifecycle and recovery

Definitive App Server rejection/overload must settle both native and Agentd state consistently. Persist and recover abort provenance across Agentd restart; do not infer it from an ordinary Cancelled state. Verify every overflow/error branch is mutation-atomic. Unknown owner acknowledgement must never release another worker's live dispatch.

### Qualification enforcement and coverage

Register `runtime.codex exact-head` and `runtime.codex synthetic-merge` as enforced checks or wire them into the existing required aggregate without weakening it. The connector did not change repository branch protection. Verify the final workflow is accepted by Actions, execute both lanes, and independently verify the actual attestation bundle. Regenerate/check the Bazel dependency lock after the new Cargo test dependency.

Eight journal cuts are not all product crash boundaries. Remaining cuts include owner dispatch/abort/fence RPC before write/after write/before response/after response, partial socket writes, App Server admission versus provider request, terminal receipt persistence and cleanup failure. Each case must assert physical request count, both owners' state, capacity, restart reconciliation and no replay.

## External work not executed

Expected-process-instance pinning for the issuer is not closed by UID/PID shape checks. Bind the independently provisioned expected executable/boot/start/cgroup identity to the connected peer, and qualify same-UID replacement and namespace changes. No production issuer key or target-host connection was available to this execution.

The quarantine document defines a resolution envelope but a production authenticated durable resolution service/CLI remains outstanding. Missing ephemeral history must continue to hold the operation; do not force-release or replay it. A local digest or a locally generated signature is not independent resolution authority.

Real issuer/key custody, real provider terminal/fault runs, statistically supported p95/p99 and resource profiles, canary, rollback, external anti-rollback recovery, and independent acceptance were **not executed**. Do not run inherited self-hosted workflows against production until their ref/environment/approval/secret boundaries have been reviewed. Repository tests use a mock provider.

## Developer reproduction

Use Rust 1.95.0, `just`, `cargo-nextest`, the repository's verified V8 artifact setup, and Linux build prerequisites. From a clean checkout:

```bash
python3 -m unittest -v scripts.tests.test_runtime_codex_receipt_v2
cd codex-rs
cargo build --locked -p codex-cli --bin codex \
  -p codex-hepta-agentd --bin codex-hepta-agentd \
  -p codex-hepta-infer-worker-host --bin hepta-infer-worker
just test --locked -p codex-hepta-infer-core
just test --locked -p codex-hepta-agentd --lib lane_b_runtime
just test --locked -p codex-hepta-infer-worker-host
just test --locked -p codex-hepta-agentd --test runtime_codex_product_e2e
```

The complete CI command inventory lives in `scripts/runtime_codex_receipt_v2.py`. Set evidence paths outside the checkout so logging cannot dirty the tested tree. Use `verify-contents` for integrity; use `verify-bundle` with an independently trusted repository, signer workflow and downloaded attestation bundle for authenticity. A failed but correctly signed receipt is still failed qualification.

## Operational stop conditions

Keep this candidate out of production until the blockers above are closed. On mismatched dispatch bindings, missing history, a failed terminal journal write, unknown abort acknowledgement, issuer identity drift or stale revocation/time frontier: stop new admission, preserve both stores and history, retain bounded digests/error codes, and escalate to the independent owner. Never repair uncertainty by deleting a journal, resetting a revision, reusing a request ID, or manufacturing a terminal receipt.
