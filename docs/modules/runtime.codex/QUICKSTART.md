# runtime.codex repository quickstart

This guide exercises the exact repository candidate against controlled test
providers. It produces **repository source evidence only**. It does not prove a
real provider, selected host, deployed issuer, independent acceptance,
activation or release.

## 1. Prerequisites

Use the checked-in Rust toolchain and lockfile. CI additionally resolves and
verifies the pinned sandboxed `rusty_v8` artifacts; follow the repository CI
setup rather than substituting an unverified local archive.

Required developer tools:

- Git with the complete candidate history needed for synthetic-merge checks;
- Python 3;
- the Rust toolchain from `rust-toolchain.toml`;
- `just` and the repository test prerequisites;
- DotSlash where App Server integration tests require it;
- Linux build dependencies used by `.github/actions/setup-ci` when running on
  Linux.

Start from a clean worktree:

```bash
git status --short
git rev-parse HEAD
git rev-parse HEAD^{tree}
```

Do not record a qualification result from a dirty worktree.

## 2. Inspect the claim boundary

Before running code, read:

```text
docs/modules/runtime.codex/REMEDIATION_STATUS.md
docs/modules/runtime.codex/FAULT_MATRIX.md
docs/modules/runtime.codex/IMPLEMENTATION_MAP.json
```

The implementation map deliberately distinguishes source presence, product
composition, current execution evidence, target-host qualification, independent
acceptance, activation and release.

## 3. Fast static checks

From the repository root:

```bash
python3 -m py_compile \
  scripts/runtime_codex_receipt_v2.py \
  scripts/runtime_codex_target_host_evidence.py

python3 -m unittest -v \
  scripts.tests.test_runtime_codex_receipt_v2 \
  scripts.tests.test_runtime_codex_target_host_evidence

cargo fmt --manifest-path codex-rs/Cargo.toml \
  --package codex-hepta-codex-adapter \
  --package codex-hepta-infer-core \
  --package codex-hepta-agent-protocol \
  --package codex-hepta-agentd \
  --package codex-hepta-infer-worker-host \
  -- --check
```

A Python syntax pass or formatter pass is not a substitute for compiling the
Rust candidate.

## 4. Focused Rust suite

From `codex-rs`:

```bash
cargo test --locked -p codex-hepta-codex-adapter -- --test-threads=1
cargo test --locked -p codex-hepta-infer-core -- --test-threads=1
cargo test --locked -p codex-hepta-agent-protocol -- --test-threads=1
cargo test --locked -p codex-hepta-agentd lane_b_runtime --lib -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host -- --test-threads=1
cargo test --locked -p codex-hepta-infer-worker-host \
  --test runtime_codex_crash_matrix -- --test-threads=1
```

The crash matrix is a closed-world state model. It verifies invariants such as
one fresh effect-entry winner, no post-fence abort, no original-operation replay
and unresolved-capacity retention. It does not replace process-level fault
injection.

## 5. Product composition test

The product E2E starts the real repository Agentd/App Server composition and
named runtime.codex caller, but uses a controlled Responses transport:

```bash
cargo test --locked -p codex-hepta-agentd \
  --test runtime_codex_product_e2e \
  runtime_codex_product_caller_commits_one_authorized_terminal_turn \
  -- --test-threads=1
```

The test must demonstrate exactly one physical provider request, exact terminal
correlation, durable authority witness and terminal settlement.

## 6. Model-only capability test

```bash
cargo test --locked -p codex-core \
  hepta_native_inference_client_has_no_model_visible_or_registered_tools \
  -- --test-threads=1
```

The deny-only client identity can remove capabilities but cannot grant a tool
effect. Any future external tool path requires its own effect owner, exact
final-use authority, durable operation identity and terminal observer.

## 7. Strict lint and build

```bash
cargo build --locked \
  -p codex-cli --bin codex \
  -p codex-hepta-agentd --bin codex-hepta-agentd \
  -p codex-hepta-infer-worker-host --bin hepta-infer-worker

cargo clippy --locked \
  -p codex-hepta-codex-adapter \
  -p codex-hepta-infer-core \
  -p codex-hepta-agent-protocol \
  -p codex-hepta-agentd \
  -p codex-hepta-infer-worker-host \
  --all-targets -- -D warnings
```

Do not downgrade strict lint, skip a platform or reuse historical output to make
an exact candidate appear green.

## 8. Machine-readable source receipt

The protected workflow `.github/workflows/runtime-codex-qualification.yml`
runs the closed-world command inventory for:

- the exact source head; and
- a deterministic ordered-parent synthetic merge.

Each command record binds source SHA, tested SHA, tree, ordered parents, command,
minimum observed test count, exit code, source cleanliness and retained log
digest. The receipt remains failed when any record is missing, invalid, skipped,
cancelled, timed out, stale or nonzero.

Local inspection of an existing bundle:

```bash
python3 scripts/runtime_codex_receipt_v2.py verify-contents \
  path/to/receipt.json \
  --records path/to/records
```

Authenticity requires the separately retained GitHub attestation bundle:

```bash
python3 scripts/runtime_codex_receipt_v2.py verify-bundle \
  path/to/receipt.json \
  --records path/to/records \
  --bundle path/to/attestation.jsonl \
  --repository TrillionniumFoundation/hepta-private-ci \
  --signer-workflow .github/workflows/runtime-codex-qualification.yml
```

Content verification without attestation proves integrity relative to supplied
files, not who produced them.

## 9. Expected local limitations

A repository developer normally does not possess:

- the production final-use signing key;
- the selected host identity and anti-rollback oracle;
- real provider audit export authority;
- an independent quarantine-resolution signer;
- an independent acceptance decision.

Do not replace these with test keys and then label the result production-ready.
Proceed to [`DEPLOYMENT.md`](DEPLOYMENT.md) only with a named protected target
host and separately operated authorities.
