# Startup paste fixture input time

## Existing evidence

The original 1dd7 Intel job reports a failure in
`startup_draft_preserves_non_bracketed_multiline_pastes_without_submitting`:
the first two newlines are absent. The complete input is a ready iterator of
34 key events, but every event still passes through terminal drawing. The log
does not record the burst state, each event interval, or which newline branch
dropped the characters. This source change does not establish that historical
branch or claim a native pass.

## Narrow change

The original positive fixture now gives its startup pump and composer clones
of one instance-owned input clock. Every upper-layer pending-newline time read
and the lower-layer input, paste flush, and submission time read uses that
clock. The terminal, input stream, rendering, exact text assertions, and
non-submission assertions remain unchanged.

Production clocks are zero-sized and always return `std::time::Instant::now()`.
Only test builds can construct or advance a controlled clock. All other
existing fixtures keep the default clock. Footer timers, terminal scheduling,
Tokio timers, and other tasks retain their original clocks; there is no global
override. The two test-only setters are the minimum connection across the
existing private pane and composer boundary.

Two separate controls call the real input paths with advancing time: a held
character is still buffered at 8 ms and flushes at 9 ms; an upper-layer newline
is retained at 120 ms and discarded at 121 ms. They do not reproduce the
production predicates in test code. Existing lower PasteBurst timing controls
and all 8/120 ms thresholds remain byte-for-byte unchanged.

## Validation boundary

The new controls are authored, not executed locally. Formatting and bounded
source checks do not replace a normal native run. No timeout, retry, success
assertion, dependency, workflow, or permission contract is changed. The original
failed case remains failed evidence until the new source runs normally.
