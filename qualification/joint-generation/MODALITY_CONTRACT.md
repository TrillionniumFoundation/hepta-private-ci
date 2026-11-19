# Qualification media envelope and canonical modality mapping

`multimodal_contract.py` is a bounded transport adapter for the generator. It
does not introduce a competing cognitive/memory contract, asset authority,
runtime controller, or production backend.

The canonical names and coordinate units remain in
[`hepta-cognitive-types/src/hnmf.rs`](../../codex-rs/hepta-cognitive-types/src/hnmf.rs):
`ModalityKindV1`, `SpanRangeV1`, and `AssetExtentV1`. The adapter recognizes all
nine canonical modality names. Its four media payload profiles map as follows:

| Media payload | Validated transport | Canonical span projection |
| --- | --- | --- |
| text | nonempty UTF-8, at most 4,096 bytes | `byte_range`, UTF-8 byte offsets |
| image | finite normalized float32 RGB, at most 64×64×3 | `pixel_rect`, pixel coordinates |
| audio | finite float32 samples in [-1,1], sample×channel shape, 8–192 kHz, at most 192,000 samples and 8 channels | `sample_range`, explicit `sampleRateHz` |
| video | finite normalized float32 RGB frame×height×width×3, at most 64×64×64×3, rational 1–240 fps, explicit per-frame timestamps | `frame_range`, explicit frame timebase numerator/denominator |

The other canonical names (`code_ast`, `gui_state`, `tool_trajectory`,
`structured_data`, `sensor`) remain recognizable reservations. Their canonical
HNMF definitions remain authoritative; this adapter does not claim to implement
their payloads. Unknown names raise `UnknownModality`. A recognized name without
a payload/backend profile raises `UnsupportedCapability` instead.

`MediaEnvelope.parse(value, now_ns=...)` validates schema
`hepta.joint-generation.media-envelope.v1`. `from_json(bytes, now_ns=...)` applies
the same validation after an independent 16 MiB wire bound. The envelope has
exact fields: `schema`, `objective_id`, `run_id`, `artifact_sha256`, `budget`,
`deadline_ns`, `decoding`, `outputs`, `streams`, `sync_tolerance_ns`. Unknown
fields, including labels at envelope/stream/timing/payload level, are rejected.

Each stream has `stream_id`, `modality`, `timing`, and `payload`. Timing has
`clock_id`, `sync_group`, `start_ns`, and `end_ns`. Intervals are nonempty,
ordered nanoseconds in the identified media clock. A shared sync group must use
the same clock and align its start/end within the declared tolerance (0–1 s).
Different groups can use independent clocks; no implicit clock conversion or
physical synchronization is claimed. Audio duration must match sample count
and sample rate. The current video profile is constant frame rate: each frame
timestamp and the clip duration must agree with its rational frame rate. A/V
times are media-clock coordinates, not the host monotonic serving deadline.

`budget` preserves the existing compute/output bounds and adds `input_bytes`.
Input bytes count owned normalized tensor bytes, UTF-8 text, and video int64
timestamps, capped at 8 MiB in aggregate. Wire JSON bytes have their separate
bound. All accepted numeric payloads are copied to owned read-only float32
arrays. This is declared transport accounting, not hardware memory or FLOPs.

`RGB8_CAPABILITIES` advertises only the existing `rgb8-instruction10-v1` backend:
one instruction text stream, one normalized 8×8 RGB image, and text/image outputs.
`to_legacy_request(envelope, expected_artifact_sha256=..., now_ns=...)` preserves
the frozen `RunSpec` identity/budget/deadline validation and validates instruction
words through the existing `serve.encode_request`. `dispatch` accepts a backend
callable only after that admission, then passes the original serving request
shape to it. The caller binds `expected_artifact_sha256` to its actual bundle
manifest digest; a mismatch stops dispatch. Generation and append-only delivery
continue to use the existing `serve.infer` and `RunSession`.

Legal audio/video envelopes therefore pass structural validation and yield
typed payloads and canonical span coordinates, but the current backend rejects
dispatch before calling the generator. There is no audio/video model or device
activation. The new interface tests include an actual RGB8 inference and
checkpoint restore through this adapter, AV admission/backend refusal,
clock/frame/sample consistency, dtype/shape/range and aggregate budget rejection.
The original r1 sources and held-out receipts are unchanged.
