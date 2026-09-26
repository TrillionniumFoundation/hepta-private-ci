# runtime.codex operations, deployment and incident runbook

This runbook covers the named native App Server caller. It does not waive the
external gates in `TECHNICAL.md`, `FAULT_MATRIX.md` or
`QUARANTINE_AND_RESOLUTION.md`.

## 1. Repository quickstart

Use the pinned repository toolchain and execute from the repository root.

```bash
rustup show
cargo fmt --all -- --check
cargo check --locked \
  -p codex-hepta-codex-adapter \
  -p codex-hepta-infer-core \
  -p codex-hepta-agent-protocol \
  -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host \
  --all-targets
cargo test --locked -p codex-hepta-codex-adapter
cargo test --locked -p codex-hepta-infer-core
cargo test --locked -p codex-hepta-agentd lane_b_runtime -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host -- --test-threads=1
cargo test --locked -p codex-hepta-agentd \
  --test runtime_codex_product_e2e \
  runtime_codex_product_caller_commits_one_authorized_terminal_turn \
  -- --test-threads=1
```

The product E2E starts real Agentd and App Server processes but uses a controlled
mock Responses provider. A pass is repository composition evidence, not
real-provider or target-host qualification.

The independent required gate is `.github/workflows/runtime-codex-required.yml`.
Its exact-head and deterministic synthetic-merge receipts are retained under
`.hepta-evidence/runtime-codex/` and, on a protected main-branch push, receive a
GitHub OIDC build-provenance attestation.

## 2. Build the named caller

```bash
cargo build --locked --release \
  --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-infer-worker-host \
  --bin hepta-infer-worker
```

The executable invocation is:

```bash
hepta-infer-worker \
  --profile native-app-server \
  --agentd-socket /absolute/owner/agentd.sock \
  --agent-id 018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12 \
  --generation 1 \
  --model MODEL \
  --journal /absolute/private/runtime-codex.journal \
  --request-id stable-operation-id \
  --maximum-in-flight 1 \
  --final-use-authority-config /absolute/private/final-use-authority.json \
  --timeout-ms 60000 \
  < prompt.txt
```

`--request-id` is a durable operation identity, not a request-scoped random
retry token. Reusing it with different semantics is a conflict. After an
accepted-or-unknown outcome, never invoke a fresh request with the same ID.

## 3. Protected final-use configuration

A production configuration is an owner- or root-owned regular file opened with
no symlink following. It must not be group/world writable. Example shape:

```json
{
  "issuer_socket": "/run/hepta-authority/runtime-codex.sock",
  "issuer_uid": 42001,
  "signer_id": "runtime-codex-final-use-2026q3",
  "verifying_key": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "authority_state_dir": "/var/lib/hepta/runtime-codex-authority-state",
  "authority_epoch": 1,
  "revocation_revision": 1,
  "revoked_grant_ids": [],
  "issuer_timeout_ms": 2000
}
```

The all-zero key above is a shape-only placeholder and must fail production
configuration review. The issuer private key never enters the worker host. Use a
dedicated service UID, a protected socket directory and externally governed key
custody. Local authority state is crash durability, not an independent
anti-rollback oracle.

## 4. Preflight checklist

Do not enable provider traffic until all checks are true:

1. exact binary digest and configuration revision are approved;
2. `runtime.codex required` is green for the exact source and merge candidate;
3. Agentd reports the expected Agent ID, generation, workspace and home root;
4. the App Server ingress socket is absolute, protected and bound to that Agent;
5. the authority socket owner, connected peer identity, signer ID and verifying
   key match the deployment record;
6. trusted time and revocation distribution are healthy and monotonic;
7. the journal directory is owner-only, on durable storage and has free space;
8. provider operation/idempotency lookup capability is known;
9. quarantine storage, resolution signer and on-call ownership are active;
10. canary, rollback and anti-rollback recovery have been rehearsed on the same
    host class.

Fail closed when any identity or frontier cannot be established.

## 5. Runtime state and safe interpretation

The important owner states are:

```text
Reserved
  -> Dispatching (durable request, no terminal fact)
  -> Running (exact turn identity observed)
  -> Released (typed terminal or exact pre-effect abort)
  -> Indeterminate / Quarantined (effect may exist; reconcile only)
```

Agentd has a corresponding run lifecycle. Exact pre-effect compensation is a
separate transition; ordinary cancellation after `Dispatched` must not be
interpreted as proof that no provider request occurred.

A successful provider response is not sufficient for authorized success. The
final receipt also requires exact request/turn correlation, terminal status,
current owner authority and the persisted final-use frontier.

## 6. Required metrics and alerts

Export bounded, non-secret metrics at the owner boundary:

- admissions, prepared dispatches, physical `turn/start` entries and terminal
  observations;
- exact pre-effect aborts and Agentd compensation retries;
- overload, typed rejection, transport-unknown and reconciliation outcomes;
- quarantined operation count and oldest quarantine age;
- duplicate/mismatched client message IDs;
- owner-health, generation and ingress-fence failures;
- authority claim latency, denial, expiry, rollback and revocation-frontier
  advances;
- App Server event lag/disconnect and interrupt outcomes;
- thread cleanup attempts, failures and orphan candidates;
- journal bytes, fsync latency, capacity occupancy and disk headroom;
- provider queue, first-token, last-token and terminal-event latency; and
- process CPU, RSS, open descriptors and socket backlog.

Never place prompts, provider output, signed grants, private keys or unrestricted
context payloads in labels or logs. Use operation IDs and digests.

Minimum alerts:

- any authority rollback, forged signature or peer-identity mismatch;
- any duplicate physical provider send for one operation;
- any successful boundary receipt without exact terminal correlation;
- growing or aged quarantine inventory;
- journal write/fsync failure or low disk space;
- owner/generation loss after effect entry;
- event-channel lag or provider disconnect rate above the qualified baseline;
- thread cleanup failure accumulation; and
- p95/p99 latency or resource use outside the accepted host profile.

## 7. Incident procedures

### Lost `turn/start` acknowledgement

1. Do not resend.
2. Retain the durable slot and exact request identity.
3. On the same connection, accept only an exact matching `turn/started` event.
4. After reopen, use `thread/read(includeTurns=true)` and require exactly one
   matching stable client message ID plus original user input.
5. Mismatch or duplicates are hard conflicts.
6. Missing ephemeral history enters quarantine.

### Provider event lag or disconnect

1. Persist cancel/stop intent where applicable.
2. Issue a bounded interrupt but do not treat interrupt acknowledgement as
   provider terminality.
3. Preserve late terminal facts without upgrading a cancelled, timed-out or
   owner-lost boundary to success.
4. Quarantine when exact terminality is unavailable.

### Agent generation or ingress change

1. Stop before final-use entry when the local pre-effect proof still exists.
2. Commit the exact local abort and reconcile Agentd through the dedicated
   abort-before-effect transition.
3. After effect entry, keep provider facts but deny success authority and
   reconcile/quarantine the operation.

### Authority rollback or signer mismatch

1. Disable admissions immediately.
2. Preserve the observed socket, peer/process identity, signer/key digest,
   epoch, revision and local store image.
3. Do not restore an older local authority directory as remediation.
4. Recover through the independently governed anti-rollback authority process.
5. Rotate epoch/key only through an approved root-of-trust transition.

### Journal corruption or disk-full

1. Fence new admissions and settlements.
2. Preserve the original file and filesystem diagnostics.
3. Do not truncate through the last uncertain record.
4. Recover to a separate path, validate the complete record chain and compare
   external owner/provider evidence.
5. Any request whose final durable boundary is uncertain remains quarantined.

## 8. Canary and rollback

A production canary is one bounded operation cohort with:

- fixed binary/configuration/source receipt;
- fixed Agentd/App Server generation and authority epoch;
- low concurrency and explicit stop thresholds;
- provider-side operation lookup enabled;
- complete latency/resource sampling; and
- no delegated external tools.

Stop the canary on any duplicate send, authority rollback, unknown owner
identity, lost durable write, unresolved cleanup growth or correctness mismatch.

Rollback changes the binary/configuration generation but does not reinterpret
existing journal records. The previous binary must understand every durable
record it may reopen, or rollback must use a compatible recovery binary.
Indeterminate operations remain with their original generation and are never
replayed merely because the deployment rolled back.

## 9. Anti-rollback recovery rehearsal

Before activation, rehearse:

1. authority state backup restore to an older revision;
2. host snapshot rollback;
3. signer-key rotation and epoch advance;
4. App Server process replacement and socket inode change;
5. Agentd generation replacement;
6. journal restore with newer external resolution frontier; and
7. quarantine resolution replay.

Every stale local state must be rejected by an external monotonic source. A
successful rehearsal produces a signed target-host receipt; repository tests
alone do not satisfy this requirement.

## 10. Performance qualification

Measure at least 30 warm operations and the agreed cold-start cohort. Record
p50, p95 and p99 for authority claim, durable prepare, `turn/start`
acknowledgement, first token, last token, terminal event, interrupt and
reconciliation. Record CPU, peak RSS, file descriptors, journal growth and
network bytes.

The accepted profile specifies hard ceilings and the overload response. Do not
convert a design target in `TECHNICAL.md` into a measured claim. Regression
comparison binds the exact binary, source tree, provider profile, host image and
configuration digest.

## 11. Release evidence boundary

The following are separate artifacts:

- repository exact-head receipt;
- deterministic synthetic-merge receipt;
- target-host issuer/process/socket receipt;
- real-provider fault-matrix receipt;
- performance/resource profile;
- canary and rollback receipt;
- anti-rollback recovery receipt; and
- independent acceptance decision.

No single artifact implies the others. Activation, promotion and release remain
false until the independent acceptance authority consumes the complete set.
