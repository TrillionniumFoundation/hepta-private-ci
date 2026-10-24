# Full Agentd dependency recovery and selected tests

Source: `d1619f1d2dd433f958d76143309011c73b4c5cf5`, unchanged clean worktree. No source or lock update, no new PR required.

The manifest and lock both pin https://github.com/kellpossible/cargo-i18n at `2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4`. Existing configured /workspace/cargo cache lacked this repository. Repository environment.toml contains no network policy; the active execution policy explicitly enables networking. No security/network settings were changed. /root/.cargo inspection returned filesystem PermissionError and was not retried; /home/agent/.cargo is absent. The writable configured cache was used.

The existing reviewed upstream dependency was obtained by Cargo through its declared URL with --locked, zero network retries and a 30s HTTP timeout. No 403/access rejection occurred, no alternate mirror or credentials were introduced. The resulting cached git checkout HEAD was independently checked as exactly the locked revision above. Original offline failure is retained in full-agentd-check.txt.

Commands (working directory repository root):

```sh
export RUSTUP_HOME=/workspace/rustup CARGO_HOME=/workspace/cargo
export CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0
export CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
export CARGO_NET_RETRY=0 CARGO_HTTP_TIMEOUT=30
export CARGO_TARGET_DIR=/workspace/task-head-full-target
export PATH=/workspace/cargo/bin:$PATH
cargo check --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd --lib
just test --locked -p codex-hepta-agentd --lib -E 'test(research_task_head_owner)'
```

Results: full workspace Agentd default-feature library check exited 0, 5m11s. Real Agentd lib-test binary compiled and linked (7m01s); 14 selected owner tests passed in 1.677s, 174 other tests not selected. This uses the repository just/nextest wrapper and actual full dependency graph, not the prior isolated harness. It does not build Agentd production binaries or execute every Agentd test or all features/workspace. Full logs include compiler dead-code warnings and wrapper metadata warnings; neither command was a strict Clippy run. No warning-free claim.

Disk before about 6.0 GiB available; after 1.6 GiB. Two build jobs, debug information disabled and incremental disabled only for resource control. No further build expansion justified. Tests are local synthetic fixtures, no provider/model access or private 2560-row replay. SHADOW_ONLY/DENY_ALL unchanged; no source-authentication, revocation, production authority, physical or scientific qualification inferred.
