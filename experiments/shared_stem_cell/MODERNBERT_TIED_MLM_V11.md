# V11: Strict physical tied-MLM checkpoint handling (research only)

The hosted pretrained mmBERT-small checkpoint is a complete stock ModernBERT
masked-language-model checkpoint. Saving a tied MLM weight may omit the decoder
alias `decoder.weight` from `model.safetensors`, because the decoder shares
**physical** storage with `model.embeddings.tok_embeddings.weight`. The previous
`LocalEncoder` rejected any `missing_keys` before it could inspect the saved
weight inventory. Its failure would be an integration problem, not evidence that
mmBERT embeddings are poor.

The opt-in V11 path retains the **entire** MLM checkpoint and the unchanged
feature-only base-model forward. For stock `ModernBertForMaskedLM` on the pinned
Transformers 4.57.1 CPU/eager profile, it may reconcile **only** an omitted
`decoder.weight` when its source embedding was serialized, the decoder and
embedding are physically the same view (pointer, dtype, device, size, stride,
storage offset, underlying storage address and byte extent), and every saved
key/value still matches the actual loaded state. Any other missing parameter,
unexpected tensor, changed model class, copied equal values or unsupported
loading report rejects. `reference_compile=False` prevents an implicit JIT
runtime mutation. Generic BERT and Encoder loading paths are preserved.

The local torch-only unit tests verify alias mechanics and failure cases. A
separate **required** installed-Transformers test creates a tiny random stock
ModernBERT MLM with safetensors, reloads it through the actual `LocalEncoder`,
executes two frozen forwards, compares repeatability and rehashes every file.
The hosted V11 workflow pins Torch and Transformers, treats any skip as failure,
and retains exact source SHA and package identity.

The miniature checkpoint is **random initialized**. This change grants no
publisher attestation, model quality, independent training comparison, NDU
utility or production activation. Existing V10 physical canaries must still
finish successfully and report original checkpoint identity before any matched
study can begin. All model selection and production gates remain **NO-GO**.
