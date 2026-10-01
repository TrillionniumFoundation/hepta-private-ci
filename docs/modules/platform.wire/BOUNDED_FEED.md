# Bounded live-stream feed contract

Live transports use `StreamingDecoder::feed`, `NegotiatedStreamingDecoder::feed`
or `WireSessionDecoder::feed`. Each returns `DecodeFeed<B>` containing an admitted
batch and a `bytes_consumed` count. Process completed frames before handling a
terminal error. When no terminal error is present, resubmit the unconsumed suffix
on the same decoder; yield to the scheduler between batches as appropriate.

A consumed-byte or completed-frame work ceiling yields without poisoning. It is
not a protocol rejection. At most one structurally admitted partial frame is
retained. Returned batches are bounded independently by consumed bytes and frame
count. Bytes already retained from a previous call may complete in the next
batch, so the output bound also includes one previously retained maximum frame.

A protocol or session-policy error preserves the successfully admitted prefix,
clears partial state and poisons the session. Further feeds consume zero bytes.
Discard the suffix and connection on a fatal error. Do not replay the returned
prefix. The policy wrapper may consume additional framing bytes before detecting
a domain-policy error; the consumed count never authorizes resuming that session.

Compatibility `push` and `push_batch` retain strict per-call input/work budgets.
They are not chunk-invariant live-transport APIs. Existing callers keep their
explicit contract; production stream integrations must migrate to the resumable
feed loop rather than arbitrarily enlarging limits.

Regression source covers coalesced input beyond the previous two-frame ceiling,
small-frame work yields, all single split positions of a good/bad/good stream,
and negotiated/frozen-policy decoder progress. This is not a claim to have
exhaustively enumerated every partition of every possible byte stream.

This document describes source behavior, not an execution receipt. Exact source
and deterministic merge tests, strict Clippy and source-map freshness must be
re-established after this change. Production activation, independent acceptance
and release remain false until independently qualified.
