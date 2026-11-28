# Explicit binary peer profile: prospective engineering qualification

The prior nine-parent JSON transport observation in #7203 moved 89,544,158
application-stream bytes. This scope connects a lossless statistics codec to
the existing peer state machine. It changes representation, not the training
objective, contribution identities, sample identities, solver or authority.
Register this protocol and exact dependencies before executing its controls.

## Transport contract

Keep JSON as the explicit default. An operator may instead construct a peer
with BinaryMessages bound to that peer's representation contract. There is no
network negotiation or fallback. Both profiles use the same SQLite admission,
CAS, batch/sample deduplication, state digest and response-request binding.

The existing outer frame remains a four-byte network-order length and at most
8 MiB. Header/body reads share one absolute two-second deadline. Binary message
bodies begin with little-endian `<4sBI>`: magic HPM1, kind 0 or 1 and canonical
metadata byte length. Kind 0 carries exactly one canonical ordinary message;
kind 1 carries offer metadata without its packet, followed by the entire
HPFTB001 contribution from pft_statistics_codec. Offer metadata is at most
8,192 bytes. No trailing bytes, alternate magic, unknown kind or text fallback
are accepted. Offers must use kind 1; other messages must use kind 0.

After decoding, the original request's canonical bytes and digest are unchanged.
Transport encoding and socket addresses therefore do not rename a contribution
or candidate. Model representation changes still require a different contract.
The frame limit remains enforced on actual encoded bytes before transmission.
All sockets remain IPv4 loopback; no authentication/confidentiality is added.

## Fixed controls

1. Execute the four retained JSON controls once against the changed service as
   compatibility regressions. This is a new source revision, not an additional
   result for the old frozen #7202 run.
2. Check complete binary offer and inventory round trips, malformed/truncated/
   extended frames, metadata shape, unknown magic/kind and contract mismatch.
   A mismatched codec must be rejected before a new ledger is created.
3. Four spawned processes on the same fixed synthetic fixture (seed 48117,
   batches 3/7/11/13, dimensions 5x2, lambda 0.2) exchange binary messages over
   a directed cycle. Every peer must independently produce the same candidate
   and agree with augmented least squares at rtol=atol=1e-7 within 20 seconds.
4. A binary receiver exits 71 after actual commit and before response. Restart
   on the original database; exact replay with its original head must return
   idempotent at revision one, preserving the independent numerical reference.
5. A JSON peer and binary peer reject each other's profile without mutation or
   automatic fallback. Unknown delivery remains unknown rather than success.

This is eight executable tests: four retained compatibility cases and four new
binary cases. Maximum whole run: 90 seconds. Freeze the implementation bytes
first, retain the first outcome and all child PID/exit evidence. A failed run
may be followed only by a source correction with separately retained evidence;
do not erase earlier costs or change thresholds. Format only after execution,
retain AST comparison and do not repeat tests solely for formatting.

Original-cache network comparison is a separate later scope. Encoding size and
transport observations must not be described as model-training acceleration,
new capability, authenticated work, learned topology or useful-work rewards.
No original scientific budget, final-test data or user trace is consumed here.
