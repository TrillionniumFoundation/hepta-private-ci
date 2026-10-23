# runtime.codex quickstart

This quickstart exercises repository-controlled source composition with a mock Responses provider. It does not qualify a real provider, target host, production issuer, activation or release.

## 1. Prerequisites

- the Rust toolchain pinned by `rust-toolchain.toml`;
- repository build dependencies documented by the root project;
- DotSlash where App Server integration tests require it;
- verified `rusty_v8` artifacts or an approved from-source build;
- Unix for final-use authority and Agentd product tests.

Run from the repository root unless a command explicitly changes directory.

## 2. Verify the exact candidate

```bash
git status --short
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
python3 scripts/hepta-lane-b-truth.py verify
```

Do not reuse a receipt produced for another commit or tree.

## 3. Focused build and tests

```bash
cd codex-rs
cargo fmt \
  -p codex-hepta-agent-protocol \
  -p codex-hepta-infer-core \
  -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host \
  -p codex-hepta-codex-adapter -- --check

cargo test -p codex-hepta-agent-protocol
cargo test -p codex-hepta-infer-core
cargo test -p codex-hepta-codex-adapter
cargo test -p codex-hepta-agentd --lib lane_b_runtime
cargo test -p codex-hepta-infer-worker-host
cargo test -p codex-hepta-agentd \
  runtime_codex_product_caller_commits_one_authorized_terminal_turn
```

The product test starts real Agentd/App Server processes but uses a controlled mock provider and a test signer. Its pass is source-composition evidence only.

## 4. Strict lint

```bash
cd codex-rs
cargo clippy \
  -p codex-hepta-agent-protocol \
  -p codex-hepta-infer-core \
  -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host \
  -p codex-hepta-codex-adapter \
  --all-targets -- -D warnings
```

## 5. Native profile configuration

The `hepta-infer-worker --profile native-app-server` path requires:

- an exact Agent ID and generation;
- an Agentd control socket;
- a model identifier;
- a bounded absolute operation deadline;
- a protected final-use authority configuration;
- an owner-private durable native journal.

See `codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md` for the authority configuration contract. Never place an issuer private key in the worker configuration.

## 6. Expected failure behavior

- stale generation or changed ingress: fail before effect entry;
- denied, expired, revoked or forged grant: fail before effect entry;
- post-dispatch final-use drift: durable two-phase `abort-before-effect`;
- exact overload before admission: typed rejection, retry-safe only under the registered policy;
- lost `turn/start` acknowledgement: same-operation reconciliation, no blind replay;
- lost history: quarantine.

## 7. Qualification receipt

The dedicated workflow writes a canonical JSON receipt containing the exact commit/tree, merge candidate identity, commands, outcomes, skipped steps, source-object digests and external gates. It signs the receipt with either a configured independent key or an explicitly labelled ephemeral CI key. An ephemeral signature proves artifact integrity within the run; it is not independent production acceptance.

## 8. Clean exit

```bash
git status --short
```

Generated source, updated lockfiles, skipped tests and dirty worktrees must be reported rather than silently discarded.
