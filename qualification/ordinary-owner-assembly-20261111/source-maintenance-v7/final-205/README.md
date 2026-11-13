# Final 205-file source and metadata candidate — unqualified

This checkpoint completes the source-bound metadata assembly and preserves the reviewed extra-gate runner. The commit containing this directory is an isolated maintenance candidate. PR #6006 remains Draft at source `d9737937eaccccf2ed2f1f79444ddec6c10d0eea`; this candidate has not replaced that PR source and has not been merged.

## Exact source identity

The [final source manifest](../FINAL_SOURCE_MANIFEST.json) is blob `443d5295721bd5399d86e54bc3b3a879fc4ec6da` (59,789 bytes; SHA256 `d987abdabd2f0a00dd4406023ddbc5d951b417afbd4959b9b5a17e880340f1d7`). Relative to the immediately preceding source commit `f9615a668f0d3a8c584a304389c4ce4c69701123`, the only product/metadata path changed here is repository-root `CALLERS.toml`. All 204 preceding manifest entries are byte-for-byte retained; the 205th entry is the exact metadata transition from actual `cd24b18a3ade8ae0a400bb2d52a27ad67f928074` to `0f0b4c835de967f90263ae9041865f5ac431615e`. Qualification files are separate evidence.

The final table is 2,151,753 bytes, SHA256 `00638bab13775377cc15a1e08aa24110d17039160b0678fae69d6476d87306fc`. The historical logical union `0f0cc13187dd3f9a09f78ef9ce33f52009c96678` was never the actual file preimage in f961. Both identities are explicit in the [replay recipe](metadata/REPLAY_RECIPE.json).

## What is implemented and statically reviewed

The preceding [nineteen-site source repairs](../clippy-repairs-v10/INDEX.json) retain actual original task handles through Shared observation, preserve original non-clone outputs/errors in unique result cells, and release the relevant mutex guard before waiting. Root/Circuit, Session/Consumer, Learning/Bootstrap, Core/AppServer and MCP custody paths are covered. The dependency change uses the existing locked futures package. Eight legacy Core test initializers explicitly lack original side evidence, preserving the strict rejection of missing evidence. No await-holding-lock lint was disabled.

The preceding [recording-window components](../recording-components/INDEX.json) add two focused cfg(test) components. They drive actual original handles to completion and cancel one waiter at the existing recording-lock boundary while two surviving waiters continue. They are engineering components with declared fixtures, not ordinary tasks or independent business consumers. They have not been executed.

The final CALLERS table has 1,011 declared boundaries, 1,011 required IDs and 600 independent protected conjuncts. It preserves all forbidden arrays in introduction order and all repeated-path conjuncts: 447 paths, 105 repeated-path groups, maximum seven conjuncts per path. No path deduplication is used.

- [Root full replay and row review](metadata/ROOT_REVIEW.json): all 25 inputs, eight semantic stages and the Outcome annex reproduce the final bytes; 54 + 94 exact operations reverse to the actual cd24 bytes. Both original-row ledgers total 2,379 entries. The 310 added-row origins and every forbidden/conjunct record were verified.
- [Independent historical and final-union review](metadata/PEER_HISTORY_AND_UNION.json): recovers original author annexes and the 699/474, 718/489 and 789/512 logical stages. The newly derived byte bridge is explicitly not substituted for historical semantic provenance.
- [Independent nineteen-site review](metadata/PEER_SHARED_SITES.md): checks 19 waits and 13 full guard rows; twelve rows change and the separate Work row is unchanged. Actual constructors, Shared cells, result locks, wait functions and relevant Drop behavior remain protected.
- [Current source inventory](metadata/SOURCE_INVENTORY.json), [caller projection](metadata/CALLER_PROJECTION.json) and [guard projection](metadata/GUARD_PROJECTION.json): 201 current Rust files contribute field indexing; 178 paths survive the original ignore policy, including core/src/session/tests.rs. The bounded caller projection covers 517 typed and 494 pattern rows with no reported missing, extra or unknown caller. It source-projects 258 guard rows, 844 function guards and 20,845 sequence markers with no reported issue. The other 342 guard sources are outside this overlay; only their metadata preservation is established.

These are pure JavaScript generation, exact byte checks and bounded source inspections. They do not execute the repository checker, typed helper, formatter, compiler or native qualification.

## Separate additional gate runner

The [unbound runner](extra-gates/UNBOUND_EXTRA_GATE_RUNNER.py), [configuration](extra-gates/CONFIG_UNBOUND.json), [complete reviewed index](extra-gates/INDEX.json) and [Root helper proof](extra-gates/ROOT_HELPER_SPAN_PROOF.json) are preserved exactly. The nine commands are four targeted crate checks, four full crate checks, and one full workspace `just test`. They retain zero retries, the existing local profile/default features and existing skip semantics.

The runner is deliberately `UNBOUND_DO_NOT_LAUNCH`. Final source identity, isolated attempt, donor identity and actual same-source fixture/helper evidence must be bound and reviewed before any execution. It rejects placeholders before mutation or process launch. One absolute 27,000-second maximum includes its 120-second evidence reserve. Each operation fixes its own end before process creation and waits only for the remaining time. Unknown completion blocks later work. Native JUnit identity is retained and rechecked before the next suite and finalization; the original collector is unchanged.

The runner does not modify the original qualification harness, does not run as Root, and does not establish business completion or physical daemon/Root exit. Synchronous I/O and process creation are not hard-real-time guarantees; observed overruns fail.

## Actual execution state

**The current 205-file candidate has not been launched and has no native qualification result.**

The last completed maintenance attempt was [v9, FAILED](../actual-v9/original-records/RESULT.json): fmt-before 0, eleven-package fix 101, fmt-after 0, binaries not run. The complete [original fix log](../actual-v9/original-records/fix-eleven-crates.log), terminal, actual formatter postimage and exact transfer proof remain preserved.

The subsequent v10 launch was bound to earlier 202-file commit `ac0037168295c898d8b2572d2274f4328dd08aef`. Its [exact tool response](../recording-components/launch-v10/START_TOOL_RESPONSE.json) returned NOT_FOUND / tunnel_client_not_seen, with no PTY session ACK and no native result. The [launch status](../recording-components/launch-v10/STATUS.json), original script/config/request and binding proof are unchanged. The managed execution environment is also currently reported unavailable. No environment, tunnel, credential or permission repair was attempted. No replacement launch key was used.

If the execution channel becomes available, the existing key `af52-future-202-maintenance-v10` must first be reconciled before any other job writes the shared operator target. A failed start response alone is not proof of a completed or absent native process.

The [last actual original qualification, V46](historical-v46/RESULT.json), used source `cbf6ca7dd619589be3e9e98755f185d34d0f7413`: ordinary 1,997/1,997, Root 16/17, overall FAILED_NATIVE_COMPONENTS. Its full caller check passed on that old source. None of those results carries over to this candidate.

## Frozen acceptance contract and remaining work

Original checker `7a6709691c372504ca11b5d2a74e14ba819fca8f`, typed helper `e23bb8aa42241b429ef5dbce5a4660853b66eb2f`, and native harness `096b5b69c1295560f3a6c9e0da51e2708a0c996c` remain unchanged. The original seven-package / Root17 roster, zero retries, 27,000-second overall and 3,600-second full-caller budgets remain required. The business deadline remains 500 ms from the original request_started_ns, without renewal or rearm.

Execution still requires authorized fmt/fix maintenance on exact source, capture of any actual source changes, corresponding metadata successors where needed, original full checker/native qualification, and the separate Core/AppServer/MCP extra gates including full-workspace just test. All outcomes must come from that exact candidate.

Business acceptance remains **0 ordinary complete chains / 0 positive adoption chains / 0 genuine NoUpdate-or-rollback chains**. Independent C, ordinary A/B materials, authentic post-publication consumption and actual daemon plus Root OS restart remain unaccepted. Failed or interrupted work is not NoUpdate.

## Chain proposal remains uninstalled

The [three-path Chain proposal](chain-uninstalled/PROPOSAL_MANIFEST.json), exact 11-operation packet, pre/post source images and independent review are preserved only in this Hepta evidence directory. Chain PR #909 remains Draft at `e338c000f26e9357ed33213624da787a3a009ed9`. The required ProfHepta / HeptaRuntime local GitHub write channel is unverified; no substitute Chain write or ref update is performed.

The proposal preserves the default four-file CLI and adds an all-or-none native readback/pin group. It adds seven refusal tests while retaining fourteen originals; these tests are unexecuted. Defer/Retain remain no_update=false, and DENY_ALL / NOT_EXPORTED / HOLD_NO_GO remain closed. No new authentic v4/native pair, independent consumer or Hepta FinalUse is accepted.

[INDEX.json](INDEX.json) pins the complete archive payload. [TREE_EXACT_DIFF.json](TREE_EXACT_DIFF.json) records the exact permitted tree delta before adding that proof itself.
