# Exact-source qualification handoff — original contracts, not new results

Prepared: 2026-11-12 19:32:52 UTC. **HOLD: the final formatted and fenced source is not frozen.** This preparation ran no H task, Cargo, test, format command or gate, and changed no repository source or ref.

The machine-readable companion is [PLAN.json](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/5961ab4f8ebad3970c0112f1a1f16bfdeda82edf): 31,035 bytes; SHA256 `1e1404e9d80723e9d001aab5d832f39f9bf8a87fd7c84826e905bc25f2e3f580`. It contains exact argv arrays, all seven focused filters, all 33 currently registered Root parents, original source/driver pins, evidence dependencies and stop rules. It is a plan, not an approved launcher or execution record.

## 1. Freeze and admission prerequisites

The immediate prepared successor is `9c4a11f61d30e9cc352bf44d56c98909d202a55d`, tree `ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7`, with parent `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`. It contains the one test-support reexport. Neither this object identity nor a predicted inventory proves native advancement, compilation or qualification.

Before qualification, retain the actual strict-forward proof, original maintenance fix/fmt results and every actual formatted postimage. Complete ordinary_path's final non-Rust fencing/QA integration against those formatted bytes; then freeze the canonical final commit/tree and actual materialization. Fill the final source identity only from that result. Any later source change creates a new qualification subject.

The existing dependency restoration is real but belongs to the 86dd seed: [RESULT](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09), [ENVIRONMENT_READY](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/8b62ac16f554c1f34ee72974637752f5a3b58aec), [normal terminal](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/3705e1ded34c017b57ee9eb13472f67df0da8e20). Reuse its actual UV/Ruff/V8/tool identities and the strict source-forward chain. Do not re-download dependencies or rewrite the old result to name the new source. Current target ownership, free space and global build/formatter concurrency still require actual observation at dispatch.

## 2. Original commands and budgets

These are recovered from the actual c0f pipeline input, the immutable native driver, and the repository workflow. Inner command deadlines and outer multi-stage budgets are distinct.

| Phase | Original command / selection | Budget | Outcome required before continuation |
|---|---|---:|---|
| Evaluator library | `just test --locked --offline -p codex-hepta-intelligence-eval --lib --retries 0 --status-level pass --success-output final --failure-output final --test-threads 2` | 3,600 s | Actual fresh runner/JUnit; 163 unique executed and passed tests, including all four frozen incomplete-evidence regressions |
| Native toolchain | Original four version commands: rustc verbose, cargo, just, cargo nextest | 120 s | Actual output; no substitution of old toolchain observations |
| Helper build | `python3 scripts/hepta_cell_test_helpers.py --package codex-hepta-infer-worker-host --output-dir <fresh records>/helpers` | 3,600 s | Actual Cargo JSONL/stderr, successful build-finished, compiler-reported `hepta-joint-propose`, pinned copied executable and source-bound manifest/env |
| Helper verification | Same helper command with `--verify-only` | 120 s before; 120 s after | Actual matching manifest, source, immutable executable bytes and environment |
| Focused | Original seven-filter OR, agentd + intelligence-eval libraries, two test threads | 7,200 s test; 12,000 s enclosing driver | Original terminal and fresh JUnit pass; existing mixed-evidence agentd case passes exactly once |
| Ordinary | All library tests in original five packages: agentd, learning-ledger, learning-artifacts, intelligence-eval, neuron; two threads | 7,200 s | Fresh JUnit and exact original named owner coverage from final-source coverage code |
| Root setup | Original UID0 setup under one fresh direct child of `/run`; source/bind/checkpoints and actual bind mount | 60 s | Actual setup; a path or metadata receipt is not setup evidence |
| Root | agentd lib, `--run-ignored only`, exact final-workflow parent expression, one thread, original `sudo -n env -i` wrapper | 7,200 s | Fresh JUnit; non-skipped names equal the complete registered parent list |
| All driver | Original `--suite all` means ordinary then Root | 21,000 s enclosing driver | Both suites and helper-after verification; failure of ordinary prevents Root |
| Root cleanup | Original ownership restoration and bind unmount when setup was attempted | 60 s unmount | Actual record; preserve errors/remaining fixture rather than imply cleanup |
| Source closure | Original unittest discovery over `qa/b4-no-bypass/*source_closure.py`, through original recorder, minimum 1 | 600 s | Actual full discovery result within original limit |
| Caller self-test | `python3 scripts/verify_hepta_callers.py self-test` | 300 s | Original execute_logged return 0, no timeout/output limit |
| Full caller proof | `python3 scripts/verify_hepta_callers.py verify` | 4,800 s | Complete final-source collector, membership and protected rows; original return 0, no timeout/output limit |

The underlying helper command remains `cargo build --locked --message-format=json-render-diagnostics -p codex-hepta-infer-worker-host --bin hepta-joint-propose`. Its offline condition comes from the original invocation environment; do not rewrite the helper recipe or pretend an old cached executable is newly source-bound.

### Existing invocation shapes

Preserve the immutable [b92 native observation driver](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/b92ddded4fce78aeb076d022471c62bf81ce2e4f), SHA256 `3c318e8d028afd0039325a531215c4add411dc5a1a0ec5016fd3448dfbf2d231`:

```text
python3 <pinned-b92-driver> --repo <final-repo> --records <fresh-focused-records>
  --source <final-head> --suite focused

python3 <pinned-b92-driver> --repo <final-repo> --records <fresh-all-records>
  --source <final-head> --suite all --root-parent /run/<fresh-direct-child>
```

Its source-bound inner test runner remains:

```text
python3 scripts/hepta_ci_exec.py --timeout-seconds 7200 --minimum-tests 1
  --output <suite-record.json> -- just test --locked --offline <original-suite-args>
  --retries 0 --status-level pass --success-output final --failure-output final
```

Source closure remains:

```text
python3 scripts/hepta_ci_exec.py --timeout-seconds 600 --minimum-tests 1
  --output <source-closure.json> --
  python3 -m unittest discover -s qa/b4-no-bypass -p '*source_closure.py' -v
```

No command here requests the full Rust workspace or adds new tests. The original all driver repeats its own toolchain/helper preparation in its fresh records directory; a focused helper PASS is not permission to skip that code.

## 3. Stack, per-test limits and exact inventories

The [original justfile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86dd56a930277e0d1aef3e475e35c2b5d60b43b7/justfile) sets `RUST_MIN_STACK=8388608` (8 MiB) and `NEXTEST_PROFILE=local`. The [run-nextest entry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86dd56a930277e0d1aef3e475e35c2b5d60b43b7/scripts/run-nextest.py) retains `--no-fail-fast`; all selected cases may report within a suite, but a failed suite stops later native suites.

The [unchanged nextest configuration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86dd56a930277e0d1aef3e475e35c2b5d60b43b7/codex-rs/.config/nextest.toml), blob `0904c42a41594d3ae4dc6f196e64f35f0b85bd2c`, defaults to 30 seconds × 2 = 60 seconds. Existing explicit durable/capacity overrides stay verbatim. In particular, the ordinary ledger history and signed growth cases already have 180- and 600-second limits. This is not permission to extend the currently failing panel/deep test deadlines. The command-level `--retries 0` remains, despite the configuration's default retry setting.

The prepared 86dd workflow has **33 exact Root parents**: the original c0f 32 plus the already registered evaluated-Version late-B-loss case. Final execution must derive that list from the actual frozen workflow, as b92 already does. An ignored Root case omitted by a default run is not coverage. Default new mechanism cases remain within the original focused filters; the final JUnit must identify what actually ran.

The four evaluator names and complete seven focused tokens are preserved in PLAN.json. The evaluator inventory check is the original 163-case contract; any genuine source inventory change must be reviewed explicitly rather than quietly weakening that check.

## 4. Reusable controls versus missing actual outputs

| Control | Reusable without changing its logic | Still needs real new-source evidence |
|---|---|---|
| Source-gates v2 `51181866…` | Exact head/tree, driver/helper hash, fresh paths/run identity and unchanged 600/300/4800 config | Actual clone, complete baseline and before/after inventories, original three gate records/logs/terminals |
| Native b92 | Exact `--source`, paths, suite, fresh Root parent and actual fixed environment; it extracts final workflow lists | Exact initial materialization/tree handoff, toolchain, helper output, each test result, fresh JUnit and required coverage |
| Original evaluator call | Same `run`, 3600/minimum1, collector and 163/four-name check | Actual final source and fresh command/collector output |
| Maintenance v4 | Original scoped fix7200/fmt900, actual restored tools and strict source-forward chain | Actual successful maintenance, complete postimages and final formatted-source integration; these remain prerequisites |
| Hosted workflow | Its existing source-controlled commands and registration are the CI contract | An actual workflow/check/status bound to final SHA; no hosted run or PASS follows from local output |

Two important interface limits are explicit. The source-gates v2 config does **not** itself enforce an expected-inventory-hash field: its original main constructs the full inventory and checks exact identity and every path against the index. A native-ready metadata field must remain backed by an actual reviewed handoff. The b92 CLI accepts source SHA, not an expected tree/full-inventory argument; its enclosing source admission must bind those actual materials.

Do not replay the entire old c0f outer pipeline blindly: it embeds historical environment, maintenance source and format-base inputs. Reuse its original commands, ordering and deadlines in a small reviewed successor handoff after current maintenance/final source freeze. No new large control framework is required.

The hosted workflow is also distinct from desktop maintenance: it retains its own ordinary/Root sequence, observer-parser controls, five-package fix, 600-second fmt at its source-controlled format base, and compile-only bins check. Do not substitute that fmt budget for the reviewed desktop 900-second contract, or claim those hosted steps have run.

## 5. Evidence and failure semantics

Preserve the original `hepta_ci_exec.py` recorder (blob `c9434b3a4afb31f80e323d543936386a2fa738de`), its 64 MiB raw-log bound, command returncode, timeout/output-limit fields, timestamps and before/after source identity. Do not independently kill Rust processes by PID. The existing recorder's bounded process-group cleanup remains its original behavior.

Before a test, move any old JUnit aside. The original collector requires a report from that execution's timestamp interval, matching terminal counts, stable bytes and exact clean source-head identity. Keep original failed logs/XML, not just summaries. Missing terminal, incomplete retention or stale/missing XML cannot become PASS or NOT_RUN after dispatch.

Preserve the original stop policies:

- Native sequence: evaluator → focused → all (ordinary → Root). A failed or unproven stage stops later native stages; final cleanup/source retention still runs.
- Source-gates v2: source-closure failure remains failure, but independent caller self-test may still run if the source is unchanged. Full caller verify runs only after self-test passes. Any actual source mutation stops subsequent source gates. Overall success requires all three.
- The original nextest `--no-fail-fast` operates inside a suite; it does not authorize starting a later suite after failure.
- The complete caller result must use final-source Rust enumeration/CALLERS/protected rows. Scoped diagnostics and historical PASS are not replacements.

### Do not conflate inventory schemas

The original native driver enumerates tracked and nonignored untracked files. Its c0f snapshot hash `c7f8f0…` is not the full physical inventory hash `cdb6cea…` produced by 5118. The latter includes ignored files and permissions.

Native JUnit is generated under `codex-rs/target/nextest/local/junit.xml` even with an external Cargo target. Preserve those real generated outputs separately and retain actual full physical observations honestly. Do not falsely describe a tracked/nonignored snapshot as a full physical inventory, silently omit output files, or demand equality with the initial clean physical inventory while pretending no report was created. Source gates use their own independent read-only clone and unchanged complete 5118 inventory.

## 6. Actual historical outcomes, which cannot transfer

| Exact c0f observation | Original record | Actual outcome |
|---|---|---|
| Evaluator lib | `f49dddd0796c3d976fc40273be49d2b9659a9af5` | 163 PASS; return 0 |
| Helper build / verify-before | `f4c385753dd372a3458db971e372fa3ba8d883ba` / `fae227350483cad21bee0603ab3567460e53c79f` | Return 0 / 0 |
| Focused | `465232e636f286344d9a4941960decee4d97c4e5` | 81 PASS / 28 FAIL, command return100, not an outer timeout |
| Native outer result | `e57711ed470fd82560be1645eb0c9e97924f9cc6` | Failed at focused; ordinary/all/Root not executed |
| Source closure | `13eedbbd41f4f10706c24d598fee2e4f58d9eb3c` | Actual timeout; command−9, recorder124; 602.954 seconds; no completed unittest total |
| Caller self-test / full proof | `4ffc489665f1982207b300394b194dbbe32f6897` / `e9a23c31c7fc7575348b1b4720a4200d45f9d632` | Both return0 without timeout/output limit; overall source gates still failed |

These records establish prior facts and original controls. They do not qualify 86dd, 9c4 or any future formatted successor.

## 7. Narrow ports handoff

The only immediate 9c4 source change is the cfg(test)-mounted `cell_q24_training_bootstrap_original_ports_tests.rs` reexport, 5,133 → 5,190 bytes, before `36289de55d67d19d5ed710044efdf7012c08d3a3`, after `1cf1bfcfb382dbaffc5b3e33b2d20acaca06b67f`. It leaves production authority, existing assertions and the original six source-entry pins untouched. ordinary_path acknowledged that final inventory/protection work must use the actual formatted postimage, not the old preimage. No CALLERS, QA or allowance changes were made by this preparation.

Even a complete new-source mechanism PASS is still not a real authorized A → original T → independent B → Adopt/complete NoUpdate → new C → daemon/Root cold recovery observation. External task authority, full frozen costs, independent outcomes and actual model-material availability remain separate evidence requirements.
