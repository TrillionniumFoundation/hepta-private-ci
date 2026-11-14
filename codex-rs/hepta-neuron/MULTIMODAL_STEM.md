# Multimodal stem

`MultimodalStemProjectionV1` is the bounded, deterministic seam between
modality-specific inputs and one shared Encoder forward. A manifest fixes the
ordered list of modality projectors. Each `ModalityProjectorV1` is an immutable
Q24 affine map with a digest over its modality id, generation, shape, and
parameters.

For one request, present modalities are projected in manifest order. A missing
slot contributes a zero vector of that projector's output width. The final
vector appends one Q24 mask value per slot (`0` for present and `1 << 24` for
missing), so the shared Encoder can learn missingness without a side channel.
The compact `u64` mask is retained in the output for receipt and audit code.

The request and output keep three provenance layers distinct:

- `source_digest` identifies the exact present modality vectors and is
  canonicalized independently of input list order;
- `modality_manifest_digest` binds generation, modality order, projector
  digests, and projector dimensions;
- `stem_digest` binds source, manifest, missing mask, and the final ordered
  Q24 vector.

Validation fails closed on empty or unknown modalities, duplicate inputs,
generation and manifest drift, width or range violations, parameter shape and
digest mismatches, and feature-budget overflow. The module performs no model
execution, persistence, learning, authority grant, or runtime mutation. Its
output can be passed as the single input vector to `SharedEncoderOwnerV1`,
with the stem digest carried alongside the existing runtime receipt in a
future evidence version.
