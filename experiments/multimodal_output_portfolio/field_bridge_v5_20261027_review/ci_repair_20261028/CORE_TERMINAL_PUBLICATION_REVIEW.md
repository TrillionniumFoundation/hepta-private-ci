# Core terminal publication: implementation review

Date: 2026-10-28. Status: **STATIC_REVIEW_COMPLETE; RUST_RUNTIME_VERIFICATION_PENDING**.

This receipt covers the seven files below in the shared `hepta` checkout, based on commit `5b7bef4e5788f2cea2546f0cb620af471b4fbcf7`. It records a source-level fix and proposed behavioral coverage, not a passing Rust test run. No scientific protocol, archive, historical failure, or study admission decision was changed.

## Finding and scope

The original `Session::send_terminal_event_and_flush` called `send_event` before its final flush. `run_finish_handoff` and `handle_task_abort` used it before clearing the active task and retiring the independent terminalization registry. A client receiving `TurnComplete` or `TurnAborted` could therefore immediately submit another turn while `has_pending_admission_fence` still rejected it. Pre-start abort shared the same early publication path.

This is a platform-independent concurrency defect and a plausible common cause of observed `NotIdle` / previous-turn-terminalizing failures. Source inspection alone does not attribute every CI failure to it; remote behavioral validation remains required.

Primary source locations in this snapshot:

- `core/src/tasks/mod.rs`: `prepare_terminal_event_and_flush` (1746), `run_finish_handoff` (3218), `run_abort_handoff` (3683), `abort_unstarted_turn` (3950), `abort_dropped_start_transition` (4032), `handle_task_abort` (4278).
- `core/src/session/turn_input.rs`: admission fence checks before and under `active_turn` (80, 295, 422, 446).
- `core/src/session/mod.rs`: production `async_channel::unbounded()` construction (562); ordinary event preparation/delivery and parent notification (2176 onward, 2439 onward).

All paths above are relative to `codex-rs/`. Function names are authoritative if subsequent formatting changes line numbers.

## Preserved invariants and commit boundary

1. Terminal preparation records MCP/trace observation and appends exactly one terminal rollout item, without updating terminal agent status or enqueuing a client event.
2. The existing flush failure-generation proof is preserved. A failed append/flush yields no recovery-confirming generation; the patch does not relabel failed persistence as durable or add a new permanent fence on this existing warning path.
3. Old task cleanup, guardian state, exact active-marker CAS, recovery publication, lifecycle callbacks, realtime handoff cleanup, and parent result forwarding finish while the old terminalization/start fence remains authoritative.
4. The final synchronous section holds `active_turn`, then the relevant registry mutex. It verifies and retires the exact identity **and** completion pair, enqueues the terminal event, then signals completion before unlocking. Missing or previously retired authority never invokes the publication callback.
5. Shutdown cannot observe an empty registry before the terminal enqueue; a waiter on the completion object cannot pass before enqueue either. A new `TurnStarted` cannot overtake that enqueue through normal admission.
6. `try_send` is nonblocking because production and inspected Session fixtures use an unbounded event channel. A closed receiver retains the existing drop/log behavior. A full channel would violate that construction invariant.
7. Before commit, cancellation, panic, timeout, or stale marker checks preserve the existing failed-closed witness rules; no replay or speculative completion is introduced. After commit, follow-up interruption cannot resurrect the old fence or be reported as an unfinished old terminalization.
8. Pending mailbox work starts after the old event, under its own start reservation. The old-owner admission bypass is no longer used by finish/abort.

Lock review: existing claim/admission paths already use `active_turn` then a registry. Registry snapshot/drain helpers release their synchronous guard before awaiting/adopting work. The publication closure has no await. No inverse registry-held await on `active_turn` was introduced.

Parent delivery remains within the old ownership fence, as requested in review, and is the last await before the commit lock. The captured status is used without a later mutation of the child's session status. This avoids adding a shutdown window that could lose the parent's final envelope. Receiving a parent mailbox result is not newly defined as a child admission barrier; the guaranteed local boundary is `TurnComplete` / `TurnAborted` delivery.

## Compatibility checks

- `protocol/src/legacy_events.rs`, `EventMsg::as_legacy_events` (625 onward): terminal variants take the default empty expansion.
- `core/src/session/turn.rs`, `realtime_text_for_event` (2222 onward): both terminal variants return `None`. The generic mirror helper has no terminal text effect; the state-mutating `maybe_clear_realtime_handoff_for_event` is explicitly retained before release.
- `core/src/session/mod.rs`, `forward_child_completion_to_parent` (2271 onward): the existing forwarding operation and error handling are reused, inside the old fence.
- `rollout/src/policy.rs`, `persisted_rollout_items` and `should_persist_event_msg`: retained terminal items are cloned without rewriting their payload. The new tests compare the whole serialized payload read back from the store with the delivered terminal payload.

## Behavioral tests added or strengthened

- `turn_complete_is_published_after_durable_cleanup_and_admission_release`
- `turn_aborted_is_published_after_durable_cleanup_and_admission_release`
- `terminal_publication_requires_exact_registry_owner_and_occurs_once`
- `terminal_event_allows_immediate_next_turn_without_admission_retry`
- Existing `cancelled_after_start_transition_promotes_detached_terminalizer`: added an assertion forbidding an early terminal while pre-start abort cleanup is gated.

The two Notify-gated tests stop at deterministic lifecycle points where the original implementation had already enqueued its terminal. They verify no terminal delivery, unchanged terminal status, a still-active admission/shutdown fence, completed expected flushes, and exactly one stored terminal. After release, they compare the delivered payload with storage, immediately admit a successor without retry, observe its `TurnStarted` before its terminal, and verify two persisted/delivered terminals without duplication. The successor is a synthetic SessionTask; it makes no provider/model call.

The ownership test covers both registry types, wrong identity, wrong completion, first valid retirement, repeated retirement, and publication before completion signalling. The public integration test uses the real regular-turn route with mocked SSE and checks the full boundary sequence `[start1, complete1, start2, complete2]` plus exactly two requests.

Remote verification should include these new tests, the existing cancellation/panic/watchdog/shutdown-adoption tests, terminal flush tests, and the core integration suite. The repository requires `just test`, not direct `cargo test`.

## Verification actually performed

- Scoped Rust 1.95 formatter and formatter check: exit 0. Stable rustfmt warned that `imports_granularity=Item` is nightly-only; all new imports already use the repository's item style.
- `git diff --check` on changed tracked files: exit 0.
- Independent architecture-agent read-only review: no new semantic, lock-order, shutdown-order, or cancellation blocker found; its requested argument-name comments were added.
- **No Rust compilation or test execution was attempted by this agent.** Local allocation had been exhausted during this session, and root reserved build/test validation for remote CI. Formatting is syntax-level evidence only, not typechecking or behavioral evidence.

## Review staging and size

Seven files total **674 added / 55 deleted = 729 changed lines** against the base above, including both new files. Production is 253 added / 55 deleted = 308 lines; behavioral coverage is 421 added lines. Root plans two consecutive commits and a single branch update to their combined head:

1. The three production files plus the public admission integration test: **373 changed lines**.
2. `session/tests.rs`, the new terminal gate test file, and `tasks/mod_tests.rs`: **356 changed lines**.

This divides review size without splitting normal completion from abort or pre-start abort. All three share the same publication defect and must move together. Both commits are intended to compile independently; that remains to be established by CI. The final head will include all coverage before remote publication/validation.

## Source identities at agent handoff

Paths below are relative to the repository root. Root may independently rerun the repository-wide scoped formatter; hashes must be rechecked before recording the final commit receipt.

| File | SHA-256 |
|---|---|
| `codex-rs/core/src/session/mod.rs` | `d16ad51556a4f4f481cccea9fc21cbb04649d7595dcd62fbb2a6c58d4dee6967` |
| `codex-rs/core/src/session/terminal_event.rs` | `9b4db5911927bd477f842bbdc901517d3f55199df4c9fe7b7f6f98dc220f49f1` |
| `codex-rs/core/src/session/tests.rs` | `d14491483442d936deb921218e637d7bd7ae4cad83da27f4372e0936648f192e` |
| `codex-rs/core/src/session/tests/terminal_event_tests.rs` | `ec51185e184a479c898f788f4ca1cd6c154a2524ffd4320f1a27fbf74b318032` |
| `codex-rs/core/src/tasks/mod.rs` | `9c8be7d120e58bef5ffe8958dbb06ca8efd94f2d4e7330dc645e49f7696c009a` |
| `codex-rs/core/src/tasks/mod_tests.rs` | `2b02ca07cf67a981b591bd49100b41a55829795de453cd00b49af33af7e143cc` |
| `codex-rs/core/tests/suite/turn_input_submission.rs` | `06e168f88662514c6f338f00c2e845fd51b9f826b57df6043d4cb97cf7117400` |
