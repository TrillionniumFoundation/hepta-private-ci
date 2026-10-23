# Optional finite-code PNG execution prototype

`measure(..., plan={..., "output_codec_profile": "local-png-codebook-v1"})`
opts into a generator-local codec table. Omission retains `rowwise-png-v1`.
Existing frozen plans and results are unchanged. No new qualification build,
formal test, content-benefit result, or measured speedup is supplied by this
implementation. Native bundle export explicitly rejects the new profile until
its serving contract is separately integrated; existing bundles remain usable.

The saved TRAIN diagnosis, not opened test scores, motivated this change:
output encoding plus its ledger consumed 76.69%–83.99% of calibration service
CPU. The code repeatedly decoded/PNG-encoded one of twelve fixed learned image
codes. The component also contains sampling, quantization, JSON and accounting;
its full CPU share cannot be advertised as PNG savings. Timing-wave variation
remains unexplained.

Preparation actually decodes all twelve codes from that generator's learned
decoder, clips/quantizes pixels, encodes PNG, hashes and base64-encodes them.
It charges the decoder validation and arithmetic before executing them, records
codec byte work, and includes imports/allocation/preparation in measured
preparation CPU. Each request still performs its original two categorical
draws, CDF selection, caption/choice creation, JSON serialization and output
accounting. Only the replaced decoding/quantization/PNG work is absent from
the request charge. The complete cost includes preparation work and CPU at the
same declared service horizon. The canonical rowwise reference/cap is retained
as the explicit normalizer; it is not a charge for unexecuted request work.

The table is bound to one `FrozenGenerator` and exact decoder bytes, with no
cross-model/global cache, labels, input cache or task-observer results. Changed,
unlocked or nonfinite decoders reject. It stores twelve immutable hash/base64
entries, with at most 65,536 encoded ASCII payload bytes. Receipts separately
record temporary decoded/quantized array payload and encoded byte counts.
These are content-byte counters, not measured Python heap size, peak memory,
RSS, energy or memory-rental cost. Actual allocation/hash/codec CPU remains
inside the existing CPU boundary. A short-lived one-request instance can cost
more than the rowwise path because it prepares all twelve codes.

Hand-array tests establish identical sampled choices, PNG/base64/hash/JSON and
RNG state across full and partial chunks, separate model/decoder isolation,
budget rejection, custom operator prices and actual native batch conservation.
They do not show that saved compute funds more useful content updates, that
content gains are stable across seeds, or that either failed scientific claim
has passed. Those TRAIN-only allocation checks remain the next integration
work. Any later formal confirmation requires a separately reviewed protocol,
all prior research records and error control across repeated confirmations.

This optimization applies to the finite twelve-code RGB8 learned decoder.
It provides no open-vocabulary, photographic, audio/video or production claim.
