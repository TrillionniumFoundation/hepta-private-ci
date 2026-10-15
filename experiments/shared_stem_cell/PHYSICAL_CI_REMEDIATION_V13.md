# V13 — Repairs derived from actual hosted CI failures

Research-only. Preserve **DENY_ALL** and all prior model-selection gates.

Source commit: \`8694c73da2ad8ef31f2c65a0c2cc5f4de6d2cfe6\`.

- V11 job 115938745235: the four tied-alias unit tests passed, but the
  installed-HF random ModernBERT MLM forward failed with
  \`unexpected keyword argument 'token_type_ids'\`. The stock BERT-style
  tokenizer supplies segment IDs, whereas \`ModernBertModel.forward\` does not
  accept them. The native-model call now requests
  \`return_token_type_ids=False\` and explicitly rejects unexpected keys.
  Non-ModernBERT tokenizer behavior remains unchanged. The hosted physical
  test asserts that the fixture tokenizer normally supplies segment IDs.
- V12 job 115938742643: tests never collected because the isolated
  environment did not install \`packaging\`; \`safetensors.torch\` imported
  it and raised \`ModuleNotFoundError\`. The V12 workflow now installs
  \`packaging==25.0\` and runs a direct import preflight.
- V10 run 38589058960: its offline contract job succeeded, but its genuine
  pretrained physical task was skipped. No model-quality claim follows.

The tests must execute anew on the exact updated commit. These corrections
are **not** evidence that mmBERT-small or Granite 97M learned more effectively.
No NDU selection, publisher attestation or production promotion is permitted.
