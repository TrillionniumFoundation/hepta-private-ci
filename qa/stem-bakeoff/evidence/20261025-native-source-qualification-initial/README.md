# First local native qualification: retained failure evidence

## Result and identity

- Run: `repair-tests-001`; command exit **100**; **635 run / 621 passed / 14 failed / 13 skipped**.
- Test phase: **43.651 s**. Entire command including compilation: **1050.613 s**.
- Started: `2026-10-24T23:44:40.435943+00:00`; completed: `2026-10-25T00:02:11.051158+00:00`.
- Base: `f2144a2451e0ca03f8c91e0c30755970cc1e4867` plus the initial four-file repair retained in `candidate-001/`.
- All **9,685** source-file digests are identical before and after. Both complete hash maps are archived, not abbreviated.
- The initial four source files were recovered from the previously frozen candidate archive and verified against the before/after maps and copy receipt.
- Actual pretrained native model calls: **0**. No rerun, build, model execution, repository edit or remote write was performed to create this package.

## Exact failed attempts

Every failed case has both original attempts in `qualification/failed-attempts.jsonl`; each includes the exact stderr, full failure block, original line bounds and block hash. The full compiler/test log and final summary remain intact.

Codes below classify the observed output only: **E** = explicit daemon-environment rejection; **B** = Broken pipe during AGENTS loading, whose immediate cause is not exposed by that attempt; **A** = post-lease full-anchor equality failure; **E-wrap** retains the six-agent context and causal chain.

| Test binary / exact case | Attempt 1 | Attempt 2 |
| --- | --- | --- |
| `authbus_text_product` / `real_agentd_without_explicit_trust_rejects_signed_text` | 0.983 s; E; log 2338 | 1.058 s; E; log 2373 |
| `authbus_text_product` / `signed_text_crosses_real_queue_once_and_current_trust_rejects_invalid_ingress` | 0.993 s; E; log 2354 | 1.293 s; E; log 2389 |
| `cognitive_product_e2e` / `real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends` | 1.306 s; E; log 2405 | 1.619 s; E; log 2469 |
| `cognitive_product_e2e` / `runtime_automation_store_failure_does_not_end_real_agentd_or_normal_turns` | 1.836 s; E; log 2421 | 1.739 s; E; log 2501 |
| `cognitive_product_e2e` / `unavailable_automation_store_keeps_real_agentd_and_app_server_ready` | 1.545 s; E; log 2437 | 1.808 s; E; log 2517 |
| `cognitive_product_e2e` / `two_real_agentd_app_servers_never_cross_recall` | 1.887 s; E; log 2453 | 2.099 s; E; log 2534 |
| `cognitive_product_e2e` / `running_consumer_observes_owner_control_grant_and_revoke_without_restart` | 3.719 s; E; log 2485 | 2.822 s; E; log 2627 |
| `cognitive_store_product_writer` / `agentd_product_host_recovers_exact_cut_into_fenced_writer_generation` | 1.188 s; A; log 2552 | 1.133 s; A; log 2605 |
| `cognitive_product_e2e` / `five_real_agents_survive_one_automation_store_failure_without_peer_stall` | 6.419 s; E; log 2573 | 10.928 s; B; log 2722 |
| `cognitive_product_e2e` / `five_running_agents_share_only_with_the_explicit_consumer` | 6.396 s; E; log 2589 | 12.321 s; E; log 2799 |
| `queue_capacity_product` / `real_agentd_manifest_capacity_bounds_its_private_app_server_queue` | 3.605 s; E; log 2647 | 3.266 s; E; log 2704 |
| `five_agent_rolling_upgrade` / `five_real_agentd_processes_roll_one_agent_without_stopping_peers` | 9.746 s; E; log 2673 | 9.641 s; E; log 2889 |
| `five_agent_rolling_upgrade` / `six_agent_fleet_lifecycle_keeps_peers_fair_and_isolated` | 13.141 s; E-wrap; log 2759 | 10.282 s; E-wrap; log 2947 |
| `two_agent_turn_recovery` / `killed_agent_recovers_same_turn_then_dispatches_queue_once_while_peer_stays_live` | 2.014 s; E; log 2835 | 2.630 s; B; log 2864 |

Across all 28 failed attempts: **24 E/E-wrap, 2 B, 2 A**. The two B retries are not rewritten as E and not separately claimed fixed.

### Original error text

- **E**, verbatim: Error: thread/start failed: error creating thread: Fatal error: Failed to initialize session: failed to load AGENTS.md instructions for environment `local`: fs sandbox helper failed with status exit status: 1: Error: invalid agentd configuration: HEPTA_FLEET_ROOT is required (code -32603)
- **B**, verbatim: Error: thread/start failed: error creating thread: Fatal error: Failed to initialize session: failed to load AGENTS.md instructions for environment `local`: Broken pipe (os error 32) (code -32603)
- **E-wrap**, original context: `Error: six-agent peer thread creation`, followed by `Caused by:` and the same `thread/start failed: ... HEPTA_FLEET_ROOT is required (code -32603)` cause. Full indentation and fleet stage output are retained in the raw attempt.
- **A**, verbatim core: `assertion `left == right` failed` at `hepta-agentd/tests/cognitive_store_product_writer.rs:204:5`. Both complete left/right anchors and the original thread IDs remain in each attempt; only their state digests differ.

## Diagnoses and subsequent candidate

- **Entrypoint:** Agentd reads daemon-only configuration before reaching its already-existing helper dispatch. The filesystem helper deliberately re-execs the same binary with a cleared controlled environment. The follow-up repair dispatches all existing helper modes first and preserves private-home initialization before dotenv/alias/runtime setup; it changes no sandbox flags.
- **Recovery fixture:** exact-cut recovery succeeds, then the production writer appends its durable lease. The follow-up retains the actual observed pre-lease anchor, preserves complete equality against the independent expected cut, and checks the later lease-induced state change separately. It does not copy the expected anchor as an observation.
- The queue/fenced-release fixture and low-level exact-current-cut recovery passed in this run; the full recovery-host fixture remains failed here.
- Root reports the follow-up fixes, shadow width repair and six-crate workflow published to PR **3807**, head `2d078bfaf6784aebafc353d929cfc5ca87e216b0`. **Qualification of that subsequent candidate is pending in this evidence.** This failed run is not evidence of the new candidate passing.
- `independent-review/` retains the original shadow review and live-context-provider investigation unchanged. In particular, Objective and NDU domain primitives do not by themselves establish a joined production context authority.

## Package contents and verification

- `qualification/`: original receipt, full raw log, complete before/after source maps, 28 exact attempt records and 14 case records.
- `candidate-001/` and `baseline-f214/`: frozen four-file candidate, patch, copy/pretest manifests and corresponding baseline source.
- `diagnosis-source/`: exact tested sources used to establish the two causes; every file is checked against the frozen source map.
- `tools/`: original download/install receipts and log, installation script, Rust 1.95.0 toolchain/component metadata; just 1.59.0 and cargo-nextest 0.9.149 archive hashes are retained. No tool-version commands were rerun for packaging.
- `followup-candidate/` and `followup-status.json`: subsequent candidate patch/manifests and explicitly pending status, kept separate from the tested candidate.
- `archive-members.json`: per-member SHA256 and size. Tar paths are relative regular files; uid/gid/mtime are fixed and file modes are read-only. External `manifest.json` binds the final tar.xz SHA256.

The package is a frozen negative-evidence snapshot. It makes no claim that the 14 failures or the wider memory-system blockers are closed.
