# runtime.fleet execution binding and delivery record

Date: 2026-09-28. Candidate: `codex/runtime-fleet-durable-owner-v1-2026-09-27`, PR #1060.

The last source-change anchor for this delivery is `3b3285b007e822911bafd867404316c010fe6d5e`. The frozen integration base is `a126987b84737dbc2ee2592442a314117bddb4a2`. Subsequent documentation commits are not implicitly qualified by that source anchor. A final receipt must identify the actual tested candidate commit/tree and, separately, the deterministic merge commit/tree.

This is an implementation and evidence record, not a declaration of completed product qualification. `CURRENT_STATE.json` is the current status projection; `LOCAL_VALIDATION.json` contains the scoped local checks and complete retained local logs. Neither file grants activation, promotion or release authority.

## 1. Delivery scope

The revision connects independently derived process requirements to the existing Fleet owner rather than adding a parallel scheduler or writer. It changes the following paths:

| Path | Implemented responsibility |
|---|---|
| `codex-rs/hepta-fleet/src/manifest_readonly.rs` | Bounded, non-mutating read of one registered Agent manifest |
| `codex-rs/hepta-fleet/src/lib.rs` | Includes that implementation in the compiled module tree |
| `codex-rs/hepta-fleet/src/durable_owner_execution.rs` | Durable execution intent, retained physical reservations, aggregate per-allocation execution demand and duplicate-identity checks |
| `codex-rs/hepta-fleet/src/durable_owner_execution_tests.rs` | Regression sources for wrong context, duplicate use, overspend, unavailable quiescence, expiry/revocation and owner reopen with a real child |
| `codex-rs/hepta-supervisor/src/fleet_start_admission.rs` | Current unexpired grant selection, signed revocation validation and execution module composition |
| `codex-rs/hepta-supervisor/src/fleet_execution_admission.rs` | Host/boot/registration/mapping binding, durable intent preparation, existing-intent adoption and shared final-effect fence |
| `codex-rs/hepta-supervisor/src/unix.rs` | Agentd and Matrixd spawn/adopt composition, command byte framing and authority-loss stop escalation |
| `codex-rs/hepta-supervisor/src/fleet_runtime_product.rs` | Ordinary pressure/capacity shrink classified separately from integrity failures |
| `scripts/runtime_fleet_qualify.py` | Read-only qualification bound to actual source and deterministic merge content |
| `scripts/test_runtime_fleet_qualify.py` | Real Git-object regression tests of the qualification mechanism |

The initial candidate already contained the Supervisor test-helper shadowing repair, a persisted monotonic host-incarnation implementation, strict read-only status parsing and the read-only snapshot/fence implementation. Those changes were reviewed and retained; they are not presented as newly originated by this delivery.

## 2. Independent inputs at the process boundary

`ProcessBinding` captures the selected-host identity at driver construction. It does not take host identity from the allocation grant being verified. On the Linux product path it reads `/etc/machine-id` and `/proc/sys/kernel/random/boot_id`, then checks the resulting opaque boot identity against the committed host incarnation. A complete operator identity override must agree with the same durable boot fence. Missing, malformed or partially configured identity inputs reject construction.

Boot identity and generation have different meanings. The former identifies a boot; the latter is a separately persisted monotonic ordinal. Numeric ordering of a boot hash and wall-clock fallback are not generation protocols. Same-boot owner restart must preserve the incarnation, and a new boot must advance it even when the new opaque identity sorts below the previous one.

`AgentManifest::read_registered` reads one bounded physical manifest without opening the registry mutation path. It validates the manifest, principal and registered workspace. The wrapper compares the actual available fleet/workspace/home/run/matrix paths with that registration. The process requirement is derived from the registered `ResourceBudget`, never copied from the grant under test.

### Physical mapping prerequisite

`HEPTA_FLEET_RESOURCE_MAPPING_PROFILE` selects an operator-reviewed `ResourceMappingPolicyV1` JSON file. The implementation requires that file to be an absolute physical path **outside the entire Fleet root**, not merely outside its `state` subdirectory. It must be root/current-owner controlled, not group/world writable and at most one MiB. The policy is captured once per driver lifetime, and its digest is included in the execution context.

Without a mapping, logical requirements remain logical. No CPU conversion coefficient is invented and unsupported logical axes are not silently discarded to make a physical grant fit. The native physical profile therefore needs a compatible reviewed mapping and allocation policy.

Agentd and Matrixd currently have separate execution contexts derived from the registered budget. Their allocation must cover the **sum** of their mapped requirements. This conservative source contract is not a claim that the existing default grant size has been qualified for simultaneous Agentd/Matrixd operation. A production profile must explicitly validate that composition rather than spend one full grant twice.

## 3. New execution protocol

The native new-process path performs these operations in order:

1. Read and validate the registered process requirements and physical layout.
2. Bind the independently observed host, committed incarnation, boot identity, manifest, common process context and mapping digest.
3. Independently sample current native capacity and pressure before preparing intent. Insufficient or unavailable capacity rejects the new effect without creating a pin.
4. Obtain one current unrevoked, unexpired allocation and a fresh signed revocation-bound final-use witness.
5. Persist an execution intent through the existing durable owner, checking current authority binding, incarnation, duplicate effect/identity and aggregate execution demand.
6. Acquire an existing-state shared owner fence and revalidate the retained hold, revocation snapshot, incarnation, live grant, principal and resources.
7. Keep that fence alive while the raw Unix driver consumes the same borrowed immutable process specification.
8. Transfer the hold into the managed-process authority monitor. Dropping the preparation fence does not delete the physical reservation.

The dispatch identity uses versioned serialization of Unix program, argument and path byte arrays. Argument boundaries, ordering and non-UTF-8 values are preserved. This avoids lossy string collisions but is not executable-image verification: the revision does not prove that a referenced executable file is immutable or install kernel CPU/memory limits.

The shared fence closes a source-level check/use gap for cooperative owner mutations. It is not a substitute for protected-host testing, filesystem protection, binary identity verification or operating-system containment.

## 4. Adoption and authority loss

Adoption does not create an intent to justify an already running process. It requires exactly one retained matching execution context and allocation, current final-use authority, and the raw driver's persisted PID/control-socket identity checks. Missing or ambiguous intent rejects adoption. Unscoped legacy library compatibility remains available outside the named product scope; it is not evidence that the product admission path executed.

While a managed process is polled, the wrapper periodically revalidates authority. A denial marks it unhealthy, requests stop and escalates to kill after the configured source grace interval. A successful signal is only a stop request. Parent exit is only a parent-exit observation. Neither releases the allocation's physical pin.

**Unclosed recovery case:** after a Supervisor crash, an already-running process with expired or revoked execution authority cannot simply pass normal adoption. A separately justified stop-only recovery path, capable of identifying and stopping that scope without granting new execution, still needs product composition and execution evidence. This delivery does not claim that such recovery is complete.

## 5. Physical reservations and quiescence

Lease expiry, revocation and host-generation fencing retire authorization. The durable physical reservation is instead rebuilt from the union of active grants and retained execution holds. An allocation is counted once in host totals while the sum of its execution-context demands must fit its grant.

Preparation rejects a repeated effect ID, a renamed effect that repeats a retained execution identity on the same allocation, or aggregate execution demand above the grant. The recovered-state reservation rebuild checks the same identity and aggregate-demand invariants. Rejection does not publish a partially updated hold set.

`reconcile_execution_group` is an all-or-none library operation. Every retained scope for an allocation must receive successful quiescence evidence from the selected-host probe before its physical pins are removed. An unavailable probe or any still-active scope preserves all pins. Intent-before-spawn ambiguity remains pinned; a missing receipt is not nonexecution evidence.

**Unclosed product case:** the complete selected-host containment/quiescence adapter is not yet wired to automatic physical release in the Unix product path. The current wrapper deliberately retains pins rather than treating parent `wait`, a kill result, lease expiry or a changed generation as proof that descendants are gone. This prevents an unsafe early-release claim but leaves reclamation and some restart/re-admission paths incomplete. It must not be advertised as completed product liveness.

The library's real-child fixture uses a controlled `/bin/sleep` child. It is useful for testing owner retention and explicit release semantics; it is not an Agentd/Matrixd descendant-containment test.

## 6. Capacity degradation and operational behavior

Ordinary pressure exceedance and a rejected capacity shrink are classified separately from corruption, invalid incarnation and execution-context errors. Maintenance does not terminate the Supervisor solely for those ordinary capacity events, refresh a stale observation or erase physical pins. The new-process path independently samples native capacity before intent preparation, avoiding reliance on the old observation's eventual TTL expiry for physical-start rejection.

This does not establish a globally persisted pressure gate for every grant-issuance API. It also does not prove nonblocking long-running behavior: synchronous owner/final-use operations and the maintenance loop's awaited blocking task still need cancellation, contention, backlog and latency measurements.

Read-only status uses existing snapshot state, does not initialize locks/generations, does not repair a frontier and does not clear holds. Unknown commands/options and unavailable state fail explicitly. Process-local counters unavailable to an independent snapshot reader are unavailable/null, not business zeros. Unsupported preflight, dry-run, mutation and Prometheus commands remain rejected rather than being documented as implemented capabilities. `OPERATIONS.md` contains the supported JSON commands.

## 7. Qualification mechanism

The qualifier requires full immutable source/base commit SHAs and a clean staged/tracked/untracked candidate. It validates candidate identity before, between and after commands. Exact-source mode requires the pinned HEAD and tree. Synthetic-merge mode requires ordered `[base, source]` parents **and** a tree identical to the actual deterministic `git merge-tree` result. Correct parents cannot launder a fabricated merge tree.

Every attempt uses a fresh evidence directory outside source. It archives the entire tracked source tree, including workspace dependencies, and binds script/workflow, archive, command logs and receipt digests. The receipt records runner/workflow provenance and separate source/base/tested commit and tree identities. Preflight and infrastructure failures produce failed receipts rather than missing or false-green evidence. Timeouts terminate and reap the command process group. No source formatting/repair, Git push or completion-flag rewrite is performed by qualification.

The full gate still includes locked Fleet and Supervisor all-target Cargo tests, the named binary check, whole-workspace formatting and strict all-feature Clippy. Those commands were not removed to make this delivery pass.

## 8. Checks actually executed for this delivery

The local workspace was a selected-file reconstruction, **not a full repository checkout**. `LOCAL_VALIDATION.json` binds eight matching remote Git blobs to their local SHA-256 values and retains the exact local logs.

| Check | Actual result | Scope |
|---|---|---|
| `python3 -B -m unittest discover -s scripts -p test_runtime_fleet_qualify.py -v` | 16 tests passed, exit 0 | Temporary real Git repositories; qualification machinery only |
| Repository-artifact Rust 1.95 `rustfmt --edition 2024 --config skip_children=true --check` on six named changed Rust files | Exit 0 | Selected-file formatting and parsing only |
| Eight source-file Git blob comparisons | Matched | Six selected Rust files and both Python files |
| Full Cargo package tests and binary check | Not executed locally | No compilation or Rust test-pass claim |
| Strict Clippy and whole-workspace formatting | Not executed locally | Selected-file rustfmt is not a substitute |
| Full exact-source and synthetic-merge qualification | Not established by these local checks | Require completed final-candidate receipts |
| Real Agentd/Matrixd containment/crash E2E and protected-host qualification | Not executed here | No deployment or independent-acceptance claim |

The formatter was obtained from the repository's formatter-export artifact, ID `10938600303`; its archive SHA-256 is `c198302f3134dbb42126a2a9163dbddf8557c6297747cf608547bb472ccfe630`. A successful formatter-export workflow is not a Fleet qualification result. The selected-file command used `skip_children=true` because the local checkout was incomplete, and its scope must remain explicit.

The 16 Python regressions cover exact source, actual merge content, forged merge trees with correct parents, wrong parent ordering, staged/tracked/untracked dirt, floating refs, preflight failure receipts, zero-exit source mutation, failed commands, unavailable programs, archive/log binding, attempt reuse, evidence placement and timeout cleanup. They do not execute the Rust product commands.

## 9. Required acceptance before closure

Complete the existing architecture rather than replacing it with another writer. Remaining acceptance must include:

- A selected-host containment driver that binds the exact process scope, enforces the intended resource profile, prevents scope escape under the reviewed threat model and observes complete quiescence before release.
- Durable recovery for intent committed before spawn, spawn completed before result persistence, stop requested before acknowledgement and quiescence observed before durable release. Ambiguity must remain discoverable and pinned until resolved.
- Stop-only recovery of already-running expired/revoked scopes after Supervisor restart, without using execution re-admission as shutdown authority.
- Real Agentd and Matrixd execution using the reviewed resource mapping and aggregate budget, followed by expiry/revocation, descendant cleanup, reopen and capacity re-admission on the same source candidate.
- Same-boot restart, lower-sorting new boot identity, rejected retired boot replay, unavailable identity source, host mismatch, requirement/grant mismatch, changed command bytes and duplicate/overspending execution cases.
- Every documented supported status command exercised against missing, corrupt, unsealed and valid existing state, checking bytes and metadata for unintended writes. Unsupported commands must return nonzero.
- Completed exact-source and deterministic synthetic-merge receipts for the final candidate, including all retained Cargo, Clippy, formatting, clean-tree and artifact checks.
- Protected-host contention, cancellation, long-backlog startup/recovery and sustained latency tests before performance claims or journal/lock optimizations.

Until those gates are satisfied, the correct state is source repairs pushed with partial validation, not completed production lifecycle or accepted release. Preserve the detailed design and historical material, update only current claims that conflict with the implemented and executed facts, and retain the draft review gate.
