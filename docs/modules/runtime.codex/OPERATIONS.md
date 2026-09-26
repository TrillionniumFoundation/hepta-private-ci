# runtime.codex operations runbook

This runbook covers repository qualification, target-host preparation, canary operation, incident response and rollback for the named `runtime.codex` App Server caller. It does not grant production authority. All examples preserve the separation between source qualification, target-host qualification, independent acceptance and release.

## 1. Components and ownership

- Codex App Server owns the canonical thread and turn execution spine.
- `hepta-codex-adapter` validates request/terminal correlation and maps retry posture; it never grants model/provider authority.
- `hepta-infer-worker-host` is the named product caller and consumes final-use authority immediately before physical `turn/start`.
- `hepta-infer-core` owns the durable native request/dispatch/observation journal.
- Agentd owns the product run lifecycle, generation, ingress and final owner-readiness decision.
- The final-use issuer and quarantine-resolution authority are independently operated services. Their private keys must not be present in the worker, Agentd or repository checkout.

## 2. Repository quickstart

Use the pinned toolchain and verified V8 artifacts used by CI. From the repository root:

```bash
python3 -m unittest scripts.tests.test_runtime_codex_receipt
cargo fmt --manifest-path codex-rs/Cargo.toml \
  --package codex-hepta-codex-adapter \
  --package codex-hepta-infer-core \
  --package codex-hepta-agent-protocol \
  --package codex-hepta-agentd \
  --package codex-hepta-infer-worker-host -- --check

cd codex-rs
cargo test --locked -p codex-hepta-codex-adapter -- --test-threads=1
cargo test --locked -p codex-hepta-infer-core -- --test-threads=1
cargo test --locked -p codex-hepta-agent-protocol -- --test-threads=1
cargo test --locked -p codex-hepta-agentd lane_b_runtime --lib -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host -- --test-threads=1
cargo test --locked -p codex-hepta-agentd \
  --test runtime_codex_product_e2e \
  runtime_codex_product_caller_commits_one_authorized_terminal_turn \
  -- --test-threads=1
```

These commands use a controlled provider in repository tests. They are not real-provider or target-host evidence. The protected workflow `.github/workflows/runtime-codex-qualification.yml` is the authoritative repository execution path because it binds exact SHA/tree, ordered synthetic-merge parents, logs, test counts and attestations.

## 3. Protected host configuration

The native caller requires protected absolute paths and explicit identities. At minimum configure:

- Agentd control socket and expected Agent id/generation;
- selected model and provider;
- final-use issuer Unix socket;
- dedicated issuer UID and protected socket ancestry;
- pinned signer id and Ed25519 verifying key;
- owner-private final-use state directory;
- nonzero authority epoch and monotonic revocation revision;
- bounded issuer timeout;
- journal location, capacity and filesystem durability profile;
- trusted-time and revocation-distribution endpoints;
- quarantine authority signer/frontier configuration.

Configuration files must be regular files opened without symlink following, root- or service-owner controlled, not group/world writable and bounded in size. State directories must be on a filesystem whose rename/fsync semantics were qualified. Never place signing private keys in these files.

## 4. Service identities and socket policy

Use distinct service accounts for Agentd, worker, final-use issuer and quarantine authority. Do not rely on a shared UID as the sole identity boundary. Target qualification must bind connected peer credentials to the expected process instance, executable identity, boot/start identity, cgroup or service unit, socket inode and protected directory chain where supported.

The issuer socket parent chain must not be writable by unrelated principals. Replacing a socket with another process under the same UID is an attack case, not a supported failover method. Planned failover uses a new independently attested process identity and monotonic authority frontier.

## 5. Startup order

1. Restore and verify anti-rollback frontier checkpoints.
2. Start trusted time/revocation distribution.
3. Start the final-use issuer with protected key custody and publish its boot identity.
4. Start the quarantine-resolution authority if this host participates in resolution.
5. Start Agentd and verify generation, workspace, home root, run root and App Server ingress.
6. Start the App Server under Agentd ownership.
7. Start the native worker with admissions closed.
8. Run local health, signer, socket, durable-store and provider preflight checks.
9. Open admissions only after the canary policy and exact qualified release digest match.

A component that cannot prove its predecessor identities remains fenced. There is no ambient fallback issuer, provider, model, state directory or App Server socket.

## 6. Canary procedure

The canary release record binds exact binary/source digest, configuration digest, target-host identity, issuer boot identity, authority/revocation frontier, provider account/endpoint, Agent generation and rollback target.

Run a bounded canary workload that proves:

- one signed final-use grant produces at most one physical provider request;
- terminal response and usage are correlated to the exact turn;
- cancellation/deadline after admission remain non-success;
- owner loss is sticky;
- overload before admission releases capacity safely;
- lost acknowledgement is reconciled without replay;
- process restart preserves unknown-operation ownership;
- no model-visible or registered tools exist for the model-only profile;
- audit and quarantine receipts are retained without secrets.

Do not widen traffic until the independent acceptor signs the canary result. Repository workflow success is not that signature.

## 7. Observability

Emit bounded structured events for:

- admission, durable prepare and owner dispatch revisions;
- final-use grant id digest, signer id, authority epoch and revocation-head digest;
- effect entry, connection/session/thread/turn correlation digests;
- overload, rejection, timeout, cancellation, owner loss and quarantine transitions;
- same-connection and reopened reconciliation attempts/results;
- orphan thread cleanup attempts;
- quarantine age and resolution frontier;
- p50/p95/p99 latency and RSS/CPU profiles by exact release digest.

Never log private keys, bearer credentials, complete prompts, unrestricted model output, raw memory content or unredacted provider responses. Retain digests and registered reason codes instead.

## 8. Alert classes

Immediate pages:

- attempted same-operation replay;
- signature, peer/process identity or revocation-frontier failure;
- anti-rollback checkpoint mismatch;
- semantic conflict for an existing operation id;
- local/Agentd dispatch digest divergence;
- terminal success without final ready owner;
- release or retry without an independently signed resolution;
- durable-store corruption or failed settlement fencing admissions.

Capacity/latency alerts use measured deployment baselines. Repository design targets must not be copied into production thresholds without target-host measurements.

## 9. Incident playbooks

### Lost `turn/start` acknowledgement

Keep the operation unresolved. First observe an exact `turn/started` event on the original connection. After restart, reopen the authenticated original generation and use `thread/read(includeTurns=true)` with the stable client message id and original input. Never create a new `turn/start` for the same operation.

### App Server history unavailable

Quarantine under `QUARANTINE_AND_RELEASE.md`. Retain capacity and evidence. Do not infer absence, success or failure. Only an independently signed resolution may close operational ownership or authorize a separate new operation.

### Owner generation or ingress changes

Fence success immediately, interrupt where possible and preserve provider facts. A later healthy response cannot restore authority for the same attempt. Re-admission requires a new generation-bound operation.

### Final-use issuer unavailable

Reject before effect. Do not fall back to a local signer, cached unsigned approval or permissive mode. Existing possibly-sent operations remain reconcile-only.

### Durable store failure

Close admissions, prevent settlement claims and preserve the last externally checkpointed frontier. Repair or restore only under the tested recovery procedure; do not delete unknown operations to regain capacity.

## 10. Rollback

Rollback is release-specific and rehearsed before canary. It must preserve interpretation of all durable records created by the candidate. Steps:

1. close admissions and drain definitely-unsent work;
2. interrupt/reconcile started work without replay;
3. quarantine unresolved effects;
4. verify the predecessor binary understands the current schema or restore a compatible state snapshot plus independently signed anti-rollback frontier;
5. start predecessor generation fenced;
6. re-establish issuer, Agentd/App Server and provider identities;
7. run rollback canaries;
8. reopen admissions only after independent approval.

Never roll back by deleting journals, resetting authority/revocation sequence, reusing an old socket identity or marking unresolved effects failed.

## 11. Performance qualification

`scripts/runtime_codex_benchmark.py` records exact candidate identity, command, p50/p95/p99 elapsed time and resident memory for a bounded repository workload. It is a source-candidate baseline, not a production capacity claim. Target-host qualification separately measures authority latency, durable prepare, Agentd RPC, provider queue, first token, terminal event, reconciliation, CPU, RSS, file descriptors and durable storage under representative concurrency and fault load.

## 12. Acceptance handoff

The handoff package contains:

- exact-head and synthetic-merge attested receipts;
- target-host identity and process/socket evidence;
- issuer key-custody, trusted-time, revocation and anti-rollback evidence;
- real-provider fault matrix and physical-request counts;
- p50/p95/p99 resource baseline;
- canary and rollback receipts;
- unresolved quarantine inventory;
- independent acceptance signature.

Absent or failed elements remain false. No repository maintainer, workflow or generated document can self-grant activation, promotion or release.
