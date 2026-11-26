# Pre-cancelled delegate admission

## Observed failure

The GNU Core library attempt on source `be271ddfa2a2d519a44112e4f176d2d8c3499c25`
reported 334 passed and one failed test. The failure was
`codex_delegate::tests::run_codex_thread_interactive_respects_pre_cancelled_spawn`:
the result did not match `TurnAborted`. That original assertion did not print the
returned value, so the log does not establish which competing result occurred.
The complete original log is retained with SHA-256
`093cdeb32b40ba34e13082291877aeeccd716ddcf20aa2c7045212c4a35fef86`.

## Contract and change

The existing approval-policy check remains first. A token already cancelled at
delegate admission now returns the existing `TurnAborted` error before channel
allocation, parent-instruction lookup, or `Session::spawn` preparation. Tokens
cancelled after that check still use the original `OrCancelExt` path; this change
does not provide atomic admission against concurrent cancellation.

This closes a source-level priority gap. The pinned Tokio 1.54.1 `select!`
implementation randomly chooses the first branch to poll by default. The pinned
tokio-util 0.7.20 cancellation future is immediately ready for an already
cancelled token, but the existing unbiased `OrCancelExt` does not give that
branch priority over another ready result. Neither the global helper nor its
fairness semantics is changed. These facts explain a possible competing result;
they do not reconstruct the unprinted value in the original failure.

Primary sources:

- [Tokio 1.54.1 select implementation](https://github.com/tokio-rs/tokio/blob/tokio-1.54.1/tokio/src/macros/select.rs)
- [tokio-util 0.7.20 cancellation token](https://github.com/tokio-rs/tokio/blob/tokio-util-0.7.20/tokio-util/src/sync/cancellation_token.rs)

## Regression scope

The existing pre-cancelled test keeps its one-second deadline and exact error
requirement. It additionally uses the existing thread-start recorder to require
zero child thread-start callbacks, and reports the returned error on failure.
The existing ordinary-delegate positive control still exercises that recorder.
A separate first-poll control requires the original exact invalid-policy error
when both the policy is invalid and the token is already cancelled. The existing
non-cancelled invalid-policy test is preserved.

The candidate has formatting, source-diff, and pin checks only. No Rust build or
test has been run for this candidate. Actual regression execution on the frozen
source remains required; the original failure and all original timeout and retry
settings remain evidence and acceptance inputs.
