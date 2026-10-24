# Terminal caller-budget parity

Exact parent #3693: 3e0ae372e9a8a6e0d5595f1ec8f6079da0a6f5d2. This is a narrow loop-return correctness fix, not a claim that the SQLite owner accepts malformed retained history or that provider authorization was bypassed.

## Contract and reproduced behavior

The crate README assigns round and total-token enforcement to the loop. The public run function takes caller Limits independently of the TurnOwner; its trait does not promise that returned frames satisfy those caller limits. Ordinary drive validates a terminal frame before returning it, but pre-cancellation/deadline cancellation returned Complete after checking only binding.

Four generic regressions (pre-cancel/deadline × maximum-round/over-total-tokens) first verify ordinary entry rejects the same budget, then expose cancellation returning Ok(Completed). The original source run executed 14 cases: 10 passed, these four failed, zero skips, exit 100. These controlled frames test the generic boundary, not production persistence.

The separate actual TaskFlow SQLite fixture creates valid retained owner limits A, commits a valid terminal observation with 12 tokens, and calls run with tighter caller limit B=11. Ordinary entry rejects B; pre-cancel incorrectly returned the valid canonical result despite B. The isolated original-source test failed exactly at that assertion (1 failed, 8 filtered, exit 100). No retained history, grant, authority or owner limit was forged or rewritten.

## Minimal repair and actual regression

Pass caller limits into private cancel and validate only its Phase::Complete result before returning it. Do not validate the whole cancellation entry: over-budget work must still be stoppable. Existing successor validation, cancellation ACK rules, persistent owner code and model/tool dispatch are unchanged. No new ledger.

After repair: generic 14/14, real TaskFlow target 9/9, and combined regression 35/35 (14 cancellation, 12 original owner-loop, 9 TaskFlow), no skips/retries, exit 0. Valid terminal returns remain intact; an over-budget CancelRequested frame still calls both controlled cancellation owners and reaches Cancelled. This control is specifically CancelRequested, not an exhaustive Model/Tools state matrix. The real fixture also verifies original A still accepts the canonical output, full frame/cursor/history remain identical, and inference/effect calls and cancellations remain zero.

Rust 1.96.0, jobs 1, dev/test debug 0, incremental 0, isolated target; exact commands/environment in invocation receipts. Original red sources/logs are retained. just fmt and diffcheck passed. Successful preformat sources are retained; independent review verified formatting-only changes. No tests were rerun after formatting as required by AGENTS. Scoped no-deps strict Clippy passed (exit 0) for the same three test targets with taskflow-owner; this is not a full-workspace or provider gate.

No UDS, external provider, model execution, BFCL, CI observation, credential/security configuration, production activation or merge. Disk remained above the 3 GiB stop threshold (more than 7 GiB at final checks). This repairs caller-budget parity when delivering a completed result; it neither rolls back previously consumed work nor changes durable admission budgets. Existing production integration and remote cancellation evidence requirements remain open.
