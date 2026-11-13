# Additional Core / AppServer / MCP test gates — fixed199 read-only plan

## Decision and scope

The required new sequence is: run focused tests for each of the four changed crates, then each complete changed-crate test gate, then the complete workspace `just test` gate required by the Core change. These runs are separate from the original seven-package qualification and Root17; that qualification harness, package set, arguments, deadlines and assertions remain unchanged.

This is a source-derived execution plan, not an execution result. This reviewer ran no h, native, Cargo, formatter, original checker, shell or ref operation. Root confirmed that the user's existing full-run authorization includes the complete workspace gate, so the repository's generic full-suite approval wording does not require another permission pause.

Inventory source: commit `14d377594626fcd8d2664aaf805436a818bec867`, tree `62a2a16cb7099eac3ce38fe134d8092bc54add03`. The maintenance run may produce a successor; bind actual tests to that final reviewed source identity and retain its real test roster. Do not carry a test PASS across an unreviewed source change.

## 1. Instructions and runner

The fixed root `AGENTS.md` blob `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a` expressly requires:

- Use `just test`; do not substitute direct `cargo test`.
- Run tests for the changed projects first.
- When common, core or protocol changed, follow those successful project tests with the complete test suite, `just test`.
- Avoid `--all-features` unless full feature coverage is specifically needed.
- The separate existing format/fix instructions remain in place; this plan does not alter or repeat the maintenance run.

There is no closer AGENTS at the exact checked `codex-rs/AGENTS.md` or four crate roots. Complete, non-truncated fixed Git trees for each relevant `src` and existing `tests` subtree contain no nested AGENTS. This is scoped evidence for these files, not a claim about unrelated repository directories.

The real justfile is at repository root, blob `a215a76cf407ace9715bca39c20497014e7dd4dc`; it sets working directory to `codex-rs`. `codex-rs/justfile` is absent. Commands below can be issued from `codex-rs`, allowing just to find its parent justfile.

Actual `test` recipe:

```text
RUST_MIN_STACK=8388608 NEXTEST_PROFILE=local python3 ../scripts/run-nextest.py "$@"
```

The wrapper `1ed63abe84267b320cbfb0123a70aac5507f4595` invokes `cargo nextest run --no-fail-fast` with the requested package, target and filter arguments. Scoped packages and graph-free `test(...)` filters may use fresh `cargo metadata --no-deps`; that changes metadata acquisition, not the requested compilation or test selection. A full run without `-p` follows normal nextest metadata. No wrapper edit is proposed.

The original `local` profile in `0904c42a41594d3ae4dc6f196e64f35f0b85bd2c` inherits the default retry count of 1 and default 30-second slow period with termination after 2 periods. The existing `test(rmcp_client)` override uses a 1-minute period and termination after 4 periods. Local AppServer integration concurrency is 4; its unit tests stay outside that integration group. Keep these settings and every existing override. Preserve all actual attempts rather than reporting a retry-success as an unqualified first-attempt success.

The checked Rust toolchain file is `917d2492264a35bc9c0feaef41878d8825870866` (Rust 1.96.0, clippy/rustfmt/rust-src). The repository CI reference pins nextest 0.9.103; this is a source reference, not evidence of the current host's installed version. Record the actual installed versions; no installation or environment repair was performed.

## 2. Focused four-crate commands

These are the proposed first mandatory stage. Each filter names actual module paths or methods read from this candidate. No mirror implementation test is added.

### Core

```sh
just test -p codex-core --lib -E 'test(session::original_shutdown::tests::) | test(thread_manager::original_shutdown::tests::) | test(codex_delegate::tests::) | test(thread_manager::tests::shutdown_all_threads_bounded_submits_shutdown_to_every_thread) | test(thread_manager::tests::cancelled_unclaimed_new_startup_removes_runtime_and_materialized_store)'
```

This covers 7 newly added real task/FD custody components (3 Session loop and 4 ThreadManager startup components), the 5 existing delegate unit tests whose construction was touched, and two existing startup/shutdown regressions. The three Unix-only socket cases among the seven run on Linux. These components do not construct a business receipt or qualify a real Root/Session startup.

Module bindings and test sources: `session/mod.rs` → `session/original_shutdown.rs` `0da95a220ed5484f419f5feb814c921c395db5ba` → `bfa76cc8a0f910b51be65ffeda49717963fa8d7b`; `thread_manager.rs` → `thread_manager_original_shutdown.rs` `5d54000ec5d0d66b0eb43c4da18528361307dd59` → `0c9e0370d897118ebcf59c8422c329cb2d8e48ba`. Existing delegate tests are `44e30df042f4a8144cb70a946427db8f631194d4`; existing ThreadManager tests are `3e2b3c40c0f161bfd391c8426260aa331790017b`.

### AppServer

```sh
just test -p codex-app-server --lib -E 'test(original_owned_shutdown::tests::) | test(request_serialization::tests::) | test(configured_mcp_runtime::tests::) | test(models_refresh_worker::tests::) | test(turn_cost_worker::tests::)'
```

This covers 8 new actual owner/job/queue/cancellation/error components, plus the existing queue, configured MCP, models-refresh and turn-cost tests at affected seams. Parent `original_owned_shutdown.rs` `8769b6ff6912729589bb86f835621387ff7fddf2` mounts `c8e64b92a7dfec68ae08c1809a3204c9d1b41870` under `original_owned_shutdown::tests`.

Historical “10 AppServer-related components” means 8 in AppServer plus 2 in Agentd, not 10 in this crate. Agentd remains in the unchanged original qualification scope. Other selected source pins: queue `58600f5dd0cc51d399ca0b5369a6275ebcf8be03`; configured MCP tests `c96c6b75b1ce75145473f196effb6ea15c414219`; models tests `989bfd8608b00334f35ee1057deb7ddbd34e15b8`; turn-cost tests `2fa57fbd608427a95e2ae617c58ff28843f16c92`.

### rmcp-client

```sh
just test -p codex-rmcp-client --lib -E 'test(stdio_server_launcher::owned_shutdown::tests::)'
```

The 6 components are mounted by `stdio_server_launcher::owned_shutdown`, with the exact `#[cfg(all(test, target_os = "linux"))]` gate in parent `868c1591cf84f1390f813ddaec5ecc97e8114454`. Test source is `5248c0e10533a1d15dcd558e2d5d7bc54ffcdf1f`. They use actual processes, retained handles, stderr, a cancelled waiter and an actual retained SDK send future; they explicitly do not run an MCP handshake or establish whole-phase completion. Linux, `/bin/sh`, `sleep`, process-group signaling and normal local process/socket support are needed. An empty selection on another OS does not satisfy this gate.

### codex-mcp

```sh
just test -p codex-mcp --lib -E 'test(connection_manager::tests::shutdown_) | test(connection_manager::tests::cancelling_startup_does_not_disable_a_ready_client) | test(runtime::tests::) | test(rmcp_client::tests::)'
```

The fixed source contains existing manager tests for pending listing shutdown, shutdown after caller cancellation and startup cancellation of a ready client, plus runtime/client tests. Sources: `connection_manager_tests.rs` `e023cf961d06cef22325112d784efc56fec038c7`, `runtime.rs` `3e2f2dd91b18cdf0f6886eb31782b9b5d5af9516`, `rmcp_client.rs` `a045b9973ff7f546860aa0a55aeb980080356b76`.

There is no dedicated test module mounted from this candidate's new `original_owned_shutdown.rs` or `rmcp_client_owned_shutdown.rs`. This command therefore exercises existing compatibility coverage; it must not be described as a newly added end-to-end strict MCP join qualification.

## 3. Complete crate gates, followed by workspace gate

After the focused stage, run the four complete package gates separately and archive each result:

```sh
just test -p codex-core
just test -p codex-app-server
just test -p codex-rmcp-client
just test -p codex-mcp
```

Then, after these project gates pass:

```sh
just test
```

The last command is the required complete workspace gate because Core changed. It has no `-p`, `-E`, `--lib` or `--test` restriction. A command with `--test all` selects the specifically named integration binary in Core/AppServer; it does not replace the workspace gate. The workspace manifest has no `default-members` restriction.

Fixed Cargo manifests:

| Directory | Actual package | Manifest Git blob | Existing targets / features |
|---|---|---|---|
| core | codex-core | df43645d3ca5e18e4ba526479a4c59cb103d3a5d | Library; config-schema binary; automatic integration targets `all`, `responses_headers`. No crate feature table or required-features. |
| app-server | codex-app-server | d3f4b4ef949e5853060ad600d80ed58bc3b85fcf | Library; `codex-app-server`, notify-capture and `exec-server` binaries; `all` integration target. No crate feature table or required-features. |
| rmcp-client | codex-rmcp-client | 1a88c3aedbe8aeccb5ce2debd97681de04d38116 | Library, 5 automatic helper binaries and 18 top-level integration-source targets. No crate feature table or required-features. |
| codex-mcp | codex-mcp | 6134f2126db203999727d05f61921836dfed06b7 | Library/unit tests; no `tests` directory, explicit test target or binary. No crate feature table or required-features. |

The manifests already enable their needed Tokio/RMCP dependency features. No additional `--features`, `--no-default-features` or `--all-features` is needed for the reviewed gates. This statement is about these Cargo manifest and source cfg conditions; it does not claim every possible platform configuration was run.

## 4. Existing integration targets for failure isolation

These tests are included in the complete crate gates. The commands are useful for isolating a concrete failure; they are not extra duplicate mandatory runs when the full crate gates already execute them.

```sh
just test -p codex-core --test all -E 'test(suite::abort_tasks::) | test(suite::codex_delegate::) | test(suite::mcp_refresh_cleanup::)'
just test -p codex-app-server --test all -E 'test(suite::v2::session_end::) | test(suite::v2::connection_handling_websocket::)'
just test -p codex-rmcp-client --test process_group_cleanup
```

Core source pins: `abort_tasks.rs` `0ddb66609968a9860252579484df664eff39ace3`, delegate integration `d8cb4483f73f4e0bbfde192a1fead25ec3fa07ac`, MCP refresh cleanup `b4b10c996f6ee5ce286b3ca342233b7e5b024b33`. AppServer: session end `93592f296745c0f8cf558616c902a934ef363856`, WebSocket connection handling `14a604fc84eead0f5bb14423b56cba7766bcd84d`. rmcp-client process group target: `ac446233f81cd37a4464daaca2b1441078ce5e00` (Unix-only).

## 5. Actual dependency and collection requirements

- The just recipe needs existing just, Python3, Cargo and cargo-nextest plus the pinned Rust toolchain/build inputs. No installation, credentials, environment repair or dependency update is requested by this report.
- The selected/new custody tests use real Tokio tasks and Unix/Linux descriptors. Broader project tests also need loopback/mock HTTP/WebSocket servers, local subprocesses and fixtures. The AppServer session-end integration uses Python3 for its real hook.
- Workspace binaries must be from the same tested source/build. The fixed `codex-utils-cargo-bin` helper `1e5dc88d75c94041228cb3e098402fb31928de4f` resolves explicit `CARGO_BIN_EXE_*` / `NEXTEST_BIN_EXE_*` metadata; it does not infer an executable from target-directory contents or build a missing one.
- Existing fixture dependencies include `codex-app-server`, `exec-server`, `test_stdio_server`, `test_streamable_http_server`, the MCP2026 helper binaries, `codex` and sometimes `codex-code-mode-host`. Same-package nextest metadata may provide relevant binaries; do not assume a filtered/package-scoped run exposes binaries from another package. Retain actual resolved binary identities.
- Linux integration also uses the real sandbox/execve helper contract. Fixed CI source `cc853510df3ab58a1991f425638eb9f39a65dd41` explicitly builds `codex-linux-sandbox` and `codex-execve-wrapper` and supplies their absolute binary paths. If equivalent current-source helper artifacts are missing, these are dependency-preparation builds, not additional test gates:
  `cargo build --locked -p codex-linux-sandbox --bin codex-linux-sandbox`;
  `cargo build --locked -p codex-shell-escalation --bin codex-execve-wrapper`.
  Other missing fixture binaries can be built from their exact package/bin target, e.g. `cargo build --locked -p codex-cli --bin codex` or `cargo build --locked -p codex-code-mode-host --bin codex-code-mode-host`; building them does not by itself supply test-run metadata. Do not rebuild artifacts already proved to belong to the exact tested source solely for this checklist.
- Existing ignored subprocess-entry tests in rmcp-client are invoked by their real parent tests. Do not add global `--run-ignored all` or remove their ignore attributes. Existing environment skip guards remain unchanged.
- The Core `skip_if_no_network!` macro (`f4e0d11e0b440b57faeba5c400e343975a0506d3`) prints a reason and returns normally when the sandbox-network flag is present. Preserve that output; a normal test return from this branch is not evidence that its integration behavior executed.

For every command record exact source head/tree and dirty state before/after, command/cwd, installed tool versions, selected profile, actual selected test names/count, complete stdout/stderr, true exit code, elapsed time, timeout/output-limit state and JUnit. The local profile emits `junit.xml`; archive its actual profile-store path before the next command can overwrite it. CI's default-profile artifact path is `$CARGO_TARGET_DIR/nextest/default/junit.xml`; this plan uses the actual `local` profile selected by just, so do not collect an older default-profile report by mistake.

Preserve first failures and every retry, distinguishing flaky-after-retry, ignored/filtered/platform-excluded cases, environment early returns, build failures and true executed passes. A zero-test focused selection, missing JUnit, incomplete process output or failed launch cannot satisfy a gate. Do not append unrelated benchmark/Bazel/schema/snapshot-update tasks unless their own triggering change applies; none is needed merely to execute these four-crate tests.

## Evidence

Complete source identities, directory-tree absence checks, Cargo targets, all commands and result obligations are in inventory Git blob `700a4e0c532167e0dad4929e3b26770943e907e8` (33,901 bytes; SHA256 `a12da2d9025ac03ebcfc47de0ce3b3d8c220eb0a85012affd115ba51ced7c343`). It contains 82 full GET/hash-verified source records.

Status: ready for Root scheduling against the final fixed source. **No tests executed and no compiler, checker, whole-phase, Root or business PASS claimed.**
