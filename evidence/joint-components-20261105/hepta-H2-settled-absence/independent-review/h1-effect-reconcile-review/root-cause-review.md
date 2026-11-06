# H1: settled absence cannot be read after its run lease is cleared

## Finding and qualification status

The two failures are a production recovery-read defect, not an omitted fixture claim and not evidence that the generation or revocation dispatch checks were bypassed. The original effect gate remains **9 passed / 2 failed**. Neither failed control can be counted as passed until the unchanged assertions complete on a new, qualified source.

This review binds Hepta commit `9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`, tree `24804b21d0306b617e12fa3f5b9454a12ed4ad41`. The six core source files were fetched by that exact commit and their complete bytes independently verified against Git blob SHA-1. Three supplementary authority files were verified in the same way. Their SHA-256, sizes and Git blobs are recorded in the two inventories.

The native receipt reports the original command `just test --locked -p codex-hepta-agentd --lib -E 'test(automation_effect_host::pq::tests::)' --no-capture --retries 0 --test-threads=1`, minimum 11, exit 100, 47.23800226603635 seconds, without timeout or output-limit overflow. Source before and after is identical and clean. The full 37,038-byte raw log was independently hashed to `ea7479a4d1d000df6d3b3d275a2837fac4e4fa809e024f10af728dfbe81b2178` and matched to that receipt.

The capture receipt identifies 11 actual test processes, including both failures, with one ELF SHA-256 `86a2c65e12fbef81586067783aa478677975e03290bcd62561938645ac1efc7e`, H1 source identity, verified wrapper ancestry and post-open process/executable identity, and no capture error. This review verifies the capture record and its association with the failed tests; it does not independently rehash the 504,265,656-byte remote ELF.

## Actual control-flow position of each failure

Both raw failures are a propagated `anyhow::Result` error, `agentd protocol error: TaskFlow owner id is missing`; they are not an assertion panic. There is exactly one production source of that error string, `AgentdAutomationEffectHost::owner_fence` in `automation_effect_host.rs` at line 1562.

| Original test | Assertions reached before the returned error | Code not reached because reconciliation propagated the error |
| --- | --- | --- |
| `generation_change_after_store_await_refuses_contact_and_keeps_consumed_nonce` | `outcome.is_err()`, boundary callback count equals 2, and `used_nonces == 1` | The `ProvenAbsent` match cannot complete; the final HTTP received-request emptiness assertion is not reached |
| `signed_revocation_after_store_await_obeys_active_effect_fence_and_never_sends` | Execute returns an error, boundary callback count equals 2, `used_nonces == 1`, and durable revocation revision remains 1 | The `ProvenAbsent` match cannot complete; the later refresh, equality to the signed revoked head, and final HTTP emptiness assertion are not reached |

This reachability conclusion follows from the exact test source and the returned-error position, rather than from added instrumentation. Raw error lines are 366 and 470; the final nextest summary at line 508 is 11 tests run, 9 passed, 2 failed, 252 skipped. The two failed names in that summary match the two captured test selectors.

The fixture is not missing an owner: `prepare_effect` constructs a real `TaskFlowFence`, registers the definition, creates and claims the run, starts it, prepares the step, and claims the step (`automation_effect_host.rs`, lines 2012–2094). The first dispatch path also successfully rebuilds the owner fence before the second boundary callback can run.

## Production sequence that produces the defect

1. `execute_at_boundary` checks store ownership and exact intent/payload, performs the first boundary callback, reads the run and obtains its current owner fence. It then calls the existing `execute_authorized_taskflow_effect` implementation (`automation_effect_host.rs`, lines 1200–1267).
2. The automation store validates the claimed step and FinalUse binding, claims the grant nonce, appends the immutable dispatch attempt, then enters `with_verified_effect` before invoking the driver (`authorized_effect.rs`, lines 748–886). The nonce remains consumed when a later boundary check refuses dispatch.
3. The driver calls the supplied boundary immediately before starting the provider worker. A generation refusal or a failed signed-feed refresh is mapped to `AuthorizedEffectDriverError::BeforeProviderContact`; provider dispatch has not started on that path (`automation_effect_host.rs`, lines 1657–1696).
4. The store records a durable `ProvenAbsent` observation with a no-contact proof, settles the attempt, and returns the original driver error (`authorized_effect.rs`, lines 886–923). Settlement first reconciles/cancels the immutable step with the same proof and then applies `RequeueProvenAbsent` (`authorized_effect.rs`, lines 1251–1265 and 1435–1534).
5. `RequeueProvenAbsent` legitimately sets the **run to `Queued`** and clears its live lease (`taskflow.rs`, lines 1521–1537 and 1634–1640). The immutable step is already `Reconciled` with `Cancelled`. The whole run is not a terminal run, and an ordinary queued run is not itself proof of absence.
6. The host's later reconciliation reads the exact durable attempt and checks its owner and destination. Its initial completed-effect fact-read only supports succeeded/failed observations. `read_terminal_effect_dispatch_receipt` explicitly returns `None` for `ProvenAbsent` (`authorized_effect.rs`, lines 694–705).
7. The host then rebuilds a fence from the mutable run projection **before** it asks the store to settle/read the durable local observation (`automation_effect_host.rs`, lines 1348–1376). The now-queued run has no owner lease, so `owner_fence` returns the observed error. The immutable absence proof and cancelled step already exist; this is a missing safe read path.

## Authority and recovery boundaries the repair must preserve

The minimal repair should expose already-settled absence as an owner-local fact read. It must verify the immutable `(owner, run, step, attempt)` history, original fence continuity, exact intent and payload digests, a `Reconciled/Cancelled` step and the same absence-proof digest in the provider ledger. A mutable status string, a missing ACK, a queued run, an error from the provider, or an unobserved attempt is insufficient.

The existing `read_terminal_taskflow_step` is not immediately sufficient: its no-fence branch requires a succeeded/failed run and matching step outcome (`taskflow_step.rs`, lines 589–704). A repair must explicitly account for the legitimate queued/cancelled-step absence state, while preserving all event verification. `verify_step_events` checks the contiguous sequence, unique commands, digests, predecessor chain, immutable intent/payload/fence and legal transitions; direct cancellation additionally requires the provider-absence command domain and receipt (`taskflow_step.rs`, lines 1299–1433).

The repair must not synthesize a new lease/fence, accept an arbitrary caller owner ID, or route unobserved/indeterminate evidence through the new fact read. Existing mutations and external status I/O must retain their original checks. `effect_dispatch_ledger.rs` passes an explicit fence to `read_verified_step_tx` when appending evidence; that validation must remain in place. A fresh physical attempt still needs a current live run lease, fresh step claim and FinalUse grant, and the existing cross-attempt absence barrier.

Current PQ authorization is separate from this fact read. `PqEffectRuntime::refresh` authenticates every presented signed feed, enforces the current contract epoch, and checks the independent external frontier; `validate_grant` enforces the PQ grant schema and lease window. The active-effect guard linearizes entry and remains held across the bounded driver call. A revocation update during that guard returns `DispatchInProgress`, and the test's durable head stays at revision 1 until the guard is released. The repair should not change any of these paths, nonce accounting, provider key derivation, approval, sandbox, or network boundaries.

## Necessary validation of a candidate

Keep both original failing controls and every original assertion. A corrected candidate needs an actual original-budget native rerun, not a renamed expected error. Focused regression evidence should distinguish settled absence from a durable-but-unsettled absence, an unknown occurrence, missing/corrupt step history, wrong intent/payload/proof, and any changed origin fence. Preserve no-contact and consumed-nonce checks, and prove the signed revocation refresh can advance only after the active fence has released.

The agent responsible for implementation is preparing a separate H2 candidate. No H1 source was modified and no Cargo, desktop process, benchmark or native rerun was started by this independent review. Candidate safety review will be recorded separately against its exact patch bytes; no H2 pass is claimed here.
