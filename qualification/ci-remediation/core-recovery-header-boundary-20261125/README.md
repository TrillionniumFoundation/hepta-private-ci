# Recovery fixture: gate the first HTTP response headers

## Recorded failure

At source `4be2e45d4c90fe539abf61814fa9b362d8922881`, both original attempts of
`suite::turn_input_submission::recover_turn_if_idle_preserves_id_and_resumes_plan_mode`
failed at the existing five-second recovery-epoch deadline. The post-interrupt
diagnostic recorded `live_seed_absent`, no active task, no candidate, no pending
terminalization, and no persistence failure. The earlier observation reported a
busy active-turn lock; it does not establish whether authority was absent then.

The preserved original regression log is 48,458 bytes with SHA-256
`56e595a458a12dac2c73bcaa1b987c1c92852d402207300ef3f997105da65ca8`.
That broader run contains other failures; this change addresses only the named
recovery fixture.

## Source-level cause

1. `core/tests/common/streaming_sse.rs` recorded the physical request and sent
   HTTP response headers before waiting on a per-chunk SSE gate.
2. `codex-api/src/rate_limits.rs` returns a default rate-limit snapshot even when
   those headers contain no rate-limit fields. `codex-api/src/sse/responses.rs`
   emits that snapshot as `ResponseEvent::RateLimits` before reading SSE bytes.
3. `core/src/session/turn.rs` gates the first provider event, including this
   header-derived event. `gate_first_provider_output` calls
   `ensure_turn_recovery_unready`; the later `recovery_seed_for_task` correctly
   rejects authority that is no longer Ready.

Holding `response.created` and the remaining SSE body therefore did not hold the
first provider event. A prior durable Ready marker alone did not prove that the
recovery window was still open when the test interrupted the turn.

## Change and verification scope

The test server now offers an explicit first-response header gate. It records
the request before waiting, consumes the gate once, and preserves the existing
per-chunk gate behavior for all callers of the original helper. The recovery
test uses this earlier boundary, preserving its original five-second deadline,
ten-millisecond polling interval, Plan mode, public epoch, turn identity,
durability ordering, and no-duplicate-input assertions.

The new real-TCP helper regression checks that the request is recorded while
all response bytes remain withheld, that releasing the gate sends the complete
first response, and that the second response does not reuse that gate. It uses
the existing helper tests' bounded read style. Production recovery, provider
event handling, cancellation, permissions, and retry policy are unchanged.

`just fmt` and `git diff --check` pass for the candidate. No behavioral test or
new build was run while preparing this patch. Qualification still requires the
original recovery integration test in `codex-core` and the new helper regression
in `core_test_support` on the candidate source; the original failed attempts
remain part of the evidence.
