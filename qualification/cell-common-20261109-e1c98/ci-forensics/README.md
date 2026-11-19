# M6 CI forensics and narrow repairs

## Scope and immutable source

This report distinguishes the original M6 checks from the current common candidate. Original M6 CI is **not green**. A new native result must bind its actual source/tree and cannot inherit a passing result from another checkout.

- Repository: `TrillionniumFoundation/hepta-private-ci`.
- Original [PR 5433](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5433), head `885dae0f3285267e9e9c49d8b43b0d009779f9e8`, tree `293ece7ffdffa2332ccfdec4fbbc4b7dcb3363cb`.
- PR base `81da60b349e32d89d0e4c4674a517a66af7e5eee`; recorded prospective-merge SHA `1fd5f73489497b16fd4a44b4bc0bd40173de7343` is metadata, not a substitute for each job's actual checkout.
- Raw logs were retained before retry. `RAW_LOG_MANIFEST.json` records exact tool-returned UTF-8 lengths and SHA-256 for 13 raw logs, preserving CRLF where present. The complete blocking-CI job inventory has 37 jobs; the purpose-built jobs endpoint's first 30 were insufficient.

## Original gate observations

| Gate | Observation | What it establishes |
| --- | --- | --- |
| [Cell native validation, attempt 2](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565757710) | Completed, failure | It is no longer in progress. |
| Cell agentd composition, job `129013941011` | Scoped suite: 7,879 passed, 104 skipped. Full workspace: 20,499 tests run, 20,498 passed, 1 failed, 134 skipped | The full workspace has one concrete Matrix restart failure. Both scoped and full commands used M6 head/tree with a clean checkout. |
| Cell mechanisms, job `129013941392` | Success | Its tested mechanism scope passed. |
| Cell configuration/actor recovery, job `129013943460` | Success | Its tested recovery scope passed. |
| [Architecture, attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565769715) | Failure | Source-head job failed obtaining V8 before its architecture native tests ran. |
| [Blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42565769736) | Run concluded cancelled; `CI required` failed | The gate reported `bazel: failure, repo-checks: cancelled`. A cancelled run must not be reported as a completed all-pass suite. |

Cell full-workspace failure is `codex-hepta-matrix-sdk::store_version_migration::encrypted_state_identity_session_and_queues_survive_restart`. Nextest tried twice, at 12.737 and 12.965 seconds, with only `Error: Initialization`. Its full-workspace nextest time was 2,105.167 seconds; the surrounding command took 3,584.710073233 seconds. Those are different cost scopes.

The uploaded Cell artifact ID is `13659324024`, ZIP SHA-256 `b44ad0e049d4901351caa16bac4a979650704bd26443a8674a31ce4c996cdd70`. The retained raw job log is 4,745,522 UTF-8 bytes. These are artifact and log identities respectively.

## Failure attribution

| Job | Observed failure | Classification and limit |
| --- | --- | --- |
| Architecture source-head `128991823205` | Python `urllib` HTTP 504 in `scripts/hepta_ci_v8.py` → `codex_package.v8` | Artifact download environment failure. Rust 1.96 setup succeeded; native architecture code did not execute. |
| macOS ARM clippy `129000593005` | DotSlash curl error 56 / HTTP 504 during Bazel preparation | Tool-download environment failure, before clippy. |
| Linux GNU lock check `129000593091` | Hermetic LLVM / rules-java / telemetry downloads returned HTTP 504, followed by generic `MODULE.bazel.lock is out of date` | A dependency-fetch failure is established. Actual lock drift is not established by that generic final message. |
| Windows shard 1 `129000593114` | bazel-lib dependency fetch HTTP 504 in smoke-header check | The native smoke-header test did not run. |
| Linux MUSL `129000593112` | `updated_actor_rechecks_current_withdrawal_and_revocation`: `RuntimeOpen(StateLocked)` while constructing prompt durable owners | Real runtime-owner test failure; not an algorithm/theory failure. Same retained-file-description lifetime mechanism as the existing inference-owner fix is a concrete repair hypothesis. |
| macOS ARM `129000593074`, Intel `129000593255` | 12 automation fixture failures each: opening a fresh Circuit owner returned `Invalid` | Fixture roots used `TempDir.path()` directly while the production store requires a canonical path. macOS `/var` aliases `/private/var`. Repair normalizes fixture roots and retains production checks. |
| Cell attempt 2 plus macOS and Windows Matrix jobs | Same encrypted restart test returns `Initialization` | Real initialization failure, not yet a proved schema migration defect. See Matrix diagnostic below. |
| Windows shard 4 `129000593067` | Legacy sandbox refuses isolation when ambient parent `FILE_DELETE_CHILD` permits bypass of deletion boundaries | Real security-contract rejection in legacy sandbox coverage. No weakening or new exception is proposed. |
| Windows shards 2/3 and macOS broad suites | Additional app-server/core/TUI/neuron/code-mode failures | Raw logs retained; these are not claimed repaired by the narrow prompt-lock and fixture cuts. |
| Repository checks `129000592665` | Cancelled | Cancellation observed; its cause is not inferred. |

## Narrow repair commits

### Prompt owner lifetime: `2cd2c890cad9b0912eb9f1e202042e2d39a8f04b`

Adds explicit owner-drop unlock to `PromptRuntimeStore` and prompt registry `Store`. Dropping only the owning file handle can leave its lock live when a concurrent fork/retained descriptor references the same file description. The lease belongs to the owner object. The change follows the already-present inference control owner treatment.

Both owners gained `owner_drop_releases_retained_descriptor_without_releasing_successor_lock`. The regression keeps the actual cloned file description open, proves a live owner still excludes a second opener, drops the owner while the descriptor remains alive, reopens durable state, and verifies closing the retained old descriptor does not release the successor's active lock. The registry additionally compares the persisted snapshot; prompt runtime retains a staged attachment.

This is a deterministic model of inherited-descriptor lifetime. It does not claim the original MUSL scheduling interleaving has been observed directly. Native verification is coordinated by root on the frozen common source.

### Canonical test fixtures: `cfae11bba5588740be9cfadb02631f18b1f4828c`

Canonicalizes the temporary parent before appending `automation` in five automation test modules: drain, recovery budget, expired recovery, learning outbox, task readback. Six construction sites change. `AutomationStore` continues to reject noncanonical production paths. No tests or assertions are removed.

### Bounded V8 recovery: `d301b2a387ff60c1f81c5ddd0e3e985e7f099aec`

The original shared resolver made one `urlopen(timeout=120)` attempt with no backoff. The repair permits at most three GET attempts for HTTP 502/503/504, with 1- and 2-second backoff and visible attempt logs. HTTP 403/404/501, TLS/certificate errors, timeouts, and hash mismatch remain fatal. Each temporary response is removed before retry. SHA-256 checks and paired archive/binding export remain unchanged.

Local validation: five download boundary tests plus ten existing CI environment tests, **15/15 passed**. `git diff --check` passed. The initial invocation without required `CODEX_REPO_ROOT` failed during module import; the recorded successful invocation supplies that existing requirement. Ruff was unavailable from the local offline cache; formatting is delegated to the common candidate formatter rather than reported passed.

```
CODEX_REPO_ROOT=/workspace/scratch/e1c98c14daab/candidate PYTHONPATH=scripts \
  python3 -m unittest scripts/codex_package/test_v8.py scripts/test_hepta_ci_v8.py
```

## One targeted Architecture retry

After retaining original logs, one retry was requested for original failed source-head job `128991823205`. GitHub accepted it. The API also scheduled a base-merge matrix leg; no blocking-CI rerun was requested and no prior run was cancelled.

Attempt 2 is now **completed, success**. Source-head job `129124162512` passed verified V8 acquisition and all selected architecture native steps, including compiled service lifecycle and actual process restart. `Architecture required` job `129139973803` passed. Base-merge job `129124164629` passed its metadata/derived-view work; its native steps were skipped, as in attempt 1. The source-head command records bind original M6 head/tree before and after, clean and unchanged. The raw retry log is 583,540 bytes, SHA-256 `9fc3aba1dc132b85e6ff157baee17d2144d5ccf6ed54359cae914e07d8d4b07e`, retained separately in `ARCHITECTURE_RETRY_LOG_MANIFEST.json`. This recovery is original M6 evidence, not verification of the common candidate's V8 retry patch. Original blocking CI and Cell workspace failures remain distinct.

## Matrix startup diagnostic

The final narrow code cut is `8857d0f0b149a1aec7546c71803453c93a4aabb5`: six lines in `codex-rs/Cargo.toml` set `profile.dev.package.matrix-sdk-store-encryption.opt-level = 3`. No Matrix production timeout, encryption parameter, migration assertion, dependency graph, lockfile, release profile, or store schema has been changed. The repository rule to update Bazel's lock applies when Rust dependencies change; this profile-only change does not alter those dependencies. Bazel does not inherit Cargo's development profile, and no Bazel Matrix pass is inferred from this experiment.

Observed source facts:

1. The wrapper applies the same five-second `MATRIX_STARTUP_REQUEST_TIMEOUT` to the whole SDK builder and maps both timeout and builder errors to `Initialization`. The actual network login separately retains its own five-second bound.
2. The fixture producer allows 120 seconds to open genuine passphrase-encrypted SDK stores and create sessions; the consumer calls the production `login_or_restore`. The default test proves same-version encrypted restart. Its two ignored external producer/consumer phases are the separately bound old-to-new migration protocol.
3. Upstream SDK 0.19.1 at `b18166c68bb958a21f0bca8b2d8320cb53583362` uses a `try_join!` future to open four SQLite stores. The unchanged vendored SQLite implementation synchronously imports each passphrase cipher in that async future. Store encryption 0.19.1 uses 200,000-round PBKDF2, also used in 0.18.
4. With explicit `homeserver_url` and the default Native sliding-sync choice, the builder does not need well-known or versions discovery. The normal supervisor default health window is 60 seconds, but this does not authorize changing the wrapper's original request deadline.

The controlled diagnosis reproduces the failure by constraining CPU, and reverses it with only the encryption dependency's compilation profile changed. Every row runs the same original encrypted restart test, retains the five-second consumer deadline and full-strength human-passphrase KDF, and verifies the diagnostic overlay is unchanged during execution.

| Build / CPU envelope | Fixture builder | Consumer SDK builder | Test result |
| --- | --- | --- | --- |
| Original debug, unrestricted | 3,140 ms | 3,113 ms | PASS, 7.909 s |
| Original debug, `cpu.max = 50000 100000` | 6,325 ms | 6,236 ms, explicit `Elapsed(())` → `Initialization` | FAIL, 14.244 s |
| Encryption dependency opt-level 3, unrestricted | 1,927 ms | 1,879 ms | PASS, 4.861 s |
| Encryption dependency opt-level 3, `cpu.max = 50000 100000` | 3,921 ms | 3,861 ms | PASS, 9.912 s |

The matched constrained runs establish debug crypto cost as a sufficient cause of the observed timeout pattern and show the narrow remedy preserves the original deadline. They do not establish the exact CPU allocation of the old hosted CI machines, nor old-to-new schema migration or a Bazel-platform result. Paths and stale sync-token removal each measured under one millisecond. Synchronous KDF work can delay when an async timeout is observed, explaining the constrained original's 6.236-second observation of its five-second timer.

The isolated diagnostic source is `/home/qq/hepta-cell-common-e1c98-20261109/matrix-diagnostic-original/source`, based on head `84b2a97c2ab3d727e27a2f5d3bc72ecfd56ae36d`, tree `eb01896296d28bfa86f6d30236e5b0d08f2942fd`. Its SDK and migration test bytes match original M6 before the diagnostic overlay. `prepare_matrix_startup_diagnostic.py` adds phase timing and exact underlying-error prints, preserving all deadlines and assertions; `run_matrix_startup_diagnostic.py` records source/diff/environment, cost, raw log hash, and a copied JUnit for each run.

The source overlay patches and diagnostic harness scripts are retained as gzip files, preserving their exact original bytes and avoiding formatter changes to historical inputs. `MANIFEST.json` records their uncompressed lengths and hashes.

The four executed diagnostic jobs were ai395 `1a1c00894a9-5e21-88f`, `1a1c00c59ad-5e21-8a2`, `1a1c01e2a1c-5e21-909`, and `1a1c020b09e-5e21-915`. Original and optimized overlays are respectively `7f0511d2e71ba114c33c9bad8b1e80890e0f6af592570914e8bc932eace65d2e` and `40d2267db410cedda58992433c732eced17c12285d8184335463a9063c78456c`. The constrained baseline log SHA-256 is `89d07867f38aa5553e9b458a002c1c32dc16d9b35308084d9abc981ade550a2f`; optimized constrained log SHA-256 is `243f92b84a8af8d8c8c74597c1eed072c579e36367dbbc3a755a2b547f257e85`. Complete receipts, logs, patches and available JUnit files are retained. No JUnit was copied by the first runner version for the initial unrestricted baseline; its full log and terminal receipt are present.

A separate attempted prebuild used `just test --no-run`, which conflicts with the wrapper's existing `--no-fail-fast`; it exited 2 before compiling. That command error is retained as `encryption-opt3-build.*`, is not a test failure, and was corrected by running the full ordinary `just test` command. Tool acknowledgement timeouts were reconciled against retained job IDs and files; they did not justify assuming execution had failed or blindly launching duplicates.

Whole subprocess costs include compilation and shared Cargo-lock waits. For example, the optimized constrained command took 123.300038 seconds including waiting/building, while the actual test took 9.912 seconds. Diagnostic overlays are not source-exact qualification evidence and remain separate from the final common-source native suite.

## Remaining verification boundary

The prompt/registry lock lifetime regressions, canonical Circuit fixtures, final common-source Matrix restart, common-source full native scope, and broad-platform CI still require their actual recorded results. The controlled Matrix A/B, original M6 test passes, targeted retry, and local Python tests do not substitute for the common frozen source. This work does not rerun exposed PRED data, change acceptance thresholds, or assert scientific gain.
