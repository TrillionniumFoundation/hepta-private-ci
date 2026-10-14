# V7: Frozen model-native pooling parity (research-only)

## Material finding

The IBM Granite Embedding 97M Multilingual R2 model card explicitly documents
CLS pooling (last_hidden_state[:, 0]) followed by unit-L2 normalization.
The existing Hepta V2/V5 path supported only attention-mask mean pooling;
therefore running granite_97m through that path is not the publisher's
standard embedding behavior and cannot be used as a fair default comparison.

Official card: https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2

mmBERT-small is a masked-language Encoder, without the same documented Granite
retrieval pooling requirement. The first mmBERT Cell-feature experiment retains
attention-mask mean as an explicitly labeled experimental pooling baseline.
This does not claim it is a publisher-certified optimum.

## Change

- execution.LocalEncoder.encode(texts, *, pooling=...) now invokes a single
  physical model forward and calls multimodal_native_pool_v7.pool_hidden_state.
  Original no-keyword calls still mean-pool exactly as before. Invalid / missing
  CLS attention, shape drift and non-finite outputs reject; no silent truncation.
- multimodal_real_encoder.EncoderProfile now preserves the declared pooling
  identity instead of hardcoding mean. Both V2 feature ingress and V5 candidate
  train/predict dispatch use that immutable identity, with versioned feature
  digests and distinct checkpoint-bound profiles.
- The non-fixture CLI granite_97m arm rejects anything other than
  cls-first-token + unit_l2 before V6 independent material admission. Mean
  pooling may still be evaluated as an explicit, differently named ablation,
  but must not be passed off as the official Granite comparison.
- V1 old mean-pooling artifact bytes, historical predictions and state journal
  are not rewritten; there is no production activation.

## Evidence boundary

Hermetic CPU PyTorch tests validate masks, CLS-vs-mean difference, explicit
identity changes, feature fanout and fail-closed behavior. CI must separately
run pinned Transformers with genuine pre-staged, independently checked
publisher-release weights. This V7 patch neither downloads mmBERT/Granite nor
proves a full frozen Encoder forward in the current host. V6 source/operator
attestation remains a distinct gate and is not publisher authentication.

The independent no-change baseline, future-window NDU selection, 64–4096 Cell
physical performance and production final-use authorizer remain unqualified.
