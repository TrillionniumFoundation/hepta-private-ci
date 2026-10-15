# V18: exact-original-safetensors recovery for the pinned mmBERT tied MLM pair

Research only; NO pretrained model-quality claim and NO production authority.

Prior hosted mmBERT attempt left exactly two Meta Parameters:
\`model.embeddings.tok_embeddings.weight\` and \`decoder.weight\`, despite a
loading report with zero missing keys. Trying \`low_cpu_mem_usage=False\`
did not fix it. V17 separately preserves the on-disk safetensors header.

V18 optionally resolves this *single exact* tied-parameter pair, but only
after the stock reviewed ModernBERTForMaskedLM 4.57.1 loader was used, the
model manifest matches the fixed \`jhu-clsp/mmBERT-small\` safetensors commit,
the original shards rehash to their frozen SHA-256s, and at least one of the
two real original tensors exists, is FP32, has the exact configured geometry,
and both saved aliases (if present) are bytewise identical. Both Meta tensors
must be the ONLY unmaterialized tensors. After binding from original bytes,
the decoder and input embedding must physically share the same Parameter.

The **unmodified** LocalEncoder checks still follow: no other Meta params,
exact saved-tensor to loaded-state equality for all tensors, only physically
proven alias exclusions, tokenizer bounds, and rehash on close. No
\`to_empty\`, random initialization, pickle loading, source substitution,
generic missing-weight fix, or production action is allowed.

Six offline PyTorch fixture tests prove acceptance/rejection mechanics only.
A separate *required* hosted Transformers test forces a pair of Meta aliases
in a real tiny random stock ModernBERT class after saving its original
safetensors, then requires LocalEncoder to recover exactly those original
bytes and complete two actual forwards. This is deliberately NOT evidence
of the genuine mmBERT model's future learning quality.

Only the genuine upstream physical canary, its exact original header and
post-load full SHA/weight proofs can establish real-source loading.
Even then paired data, future no-change baseline and independent NDU remain
unqualified. Production remains DENY_ALL.

## V17 physical on-disk proof (actual upstream source)

V17 GitHub run 38666811093, artifact 11943069008, SHA-pinned
`jhu-clsp/mmBERT-small@0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`:

- safetensors index: **137** original tensors;
- original `decoder.weight`: **present**, FP32 [256000, 384];
- original `model.embeddings.tok_embeddings.weight`: **absent**;
- original tensor-header census SHA256:
  `62527c9096e5c2cb64ed9ccbdf8d5e16f123eddc65f85dc3829eea0744528387`.

This proves an asymmetrical original saved-key inventory, not that the
Transformers loader correctly materialized it. The required V18 hosted test
now deliberately creates a decoder-only *random miniature* checkpoint
matching this exact saved-key convention and verifies that the decoder
source becomes one physically shared stock MLM Embedding/Decoder Parameter.
The test must never be cited as proof of genuine pretrained utility.
