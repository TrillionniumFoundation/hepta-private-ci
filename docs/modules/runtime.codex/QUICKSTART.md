# runtime.codex developer quickstart

This quickstart exercises repository-controlled composition with a mock Responses provider. It does **not** establish a real-provider, target-host, activation, acceptance, promotion, or release claim.

## Prerequisites

- Rust toolchain pinned by `rust-toolchain.toml`;
- `just` and `cargo-nextest` at the versions installed by repository CI;
- Linux build packages `build-essential`, `pkg-config`, and `libcap-dev`;
- verified `rusty_v8` artifacts resolved by `.github/actions/setup-rusty-v8`.

From the repository root, use the repository workflow to provision CI prerequisites. Do not execute `.github/actions/setup-ci/action.yml` as a shell script. In an equivalent prepared environment, run:

```bash
cd codex-rs
just test --locked -p codex-hepta-codex-adapter --test-threads=1
just test --locked -p codex-hepta-agent-protocol --test-threads=1
just test --locked -p codex-hepta-agentd lane_b_runtime --test-threads=1
just test --locked -p codex-hepta-infer-core native --test-threads=1
just test --locked -p codex-hepta-infer-worker-host --test-threads=1
just test --locked -p codex-hepta-agentd \
  runtime_codex_product_caller_commits_one_authorized_terminal_turn \
  --test-threads=1
```

Use `.github/workflows/runtime-codex-qualification.yml` as the executable reference for a clean exact-head environment. That workflow binds the candidate SHA/tree, runs the focused suites, emits a canonical receipt, and attests the receipt on a push.

## What the product E2E proves

The product E2E starts the real Agentd/App Server composition, uses the named `AppServerModelDriver`, obtains an independently signed **test** final-use grant, submits exactly one request to a controlled mock provider, and persists terminal correlation. It deliberately does not contain a production issuer key or real provider credential.

## Common local failures

- Missing V8 override: run the same `setup-rusty-v8` action used by CI or use a runner image that already supplies the verified artifacts.
- `ProductBindingRequired`: the test constructed an adapter intent without the real App Server connection/session binding.
- `Indeterminate`: do not rerun the operation under a new identity; inspect the durable record and use the same-operation reconciliation path.
- Final-use denial: verify the exact payload, deadline, issuer head, Agent generation, App Server session, and connection identity before changing any policy.
