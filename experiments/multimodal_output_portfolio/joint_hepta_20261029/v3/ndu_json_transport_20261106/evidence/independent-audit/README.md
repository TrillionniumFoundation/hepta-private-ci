# Reproduce the independent receipt audit

This folder contains a read-only internal audit of the single JSON transport
development procedure published in draft PR #4999. It does not invoke the runner,
load a language model, generate text, execute SQL or read through a source tool.
It loads the fixed tokenizer and hashes model tensor data; it never executes
content found inside a model answer. Original execution artifacts are inputs.

`AUDIT.md` explains the result and limitations. `audit-attempt-01.json` preserves
the first audit output. `audit_json_transport.py` independently reconstructs
execution stages and ledger accounting. `receipt_checks.py` provides data-only
source, model-byte, tokenizer, decoder and public-prompt checks. The parameter
hashing method deliberately reuses the earlier BF16-to-FP32 audit method.

`remote-anchor.json` records direct immutable GitHub source readbacks and exact
local/remote identity matches. `remote-sources.json` preserves all returned
base64 source bytes; `remote-metadata.json` preserves the retrieved commit and PR
metadata. A compressed copy of those two raw remote readbacks is provided for
repository retention. The anchor is not an external signature or preregistration.

After restoring the original qualification and pilot artifact directories, run
the following with the already acquired model/runtime. Choose a new output path;
the audit refuses to overwrite a result. The host Python argument is the exact
interpreter used by the original runner and is part of each tool-command hash.

```bash
/workspace/scratch/3f6a885bb83c/round3_resources/followup_lm/venv/bin/python -B \
  audit_json_transport.py \
  --repo /workspace/scratch/3f6a885bb83c/hepta-research \
  --resources /workspace/scratch/3f6a885bb83c/round3_resources \
  --runtime /workspace/scratch/3f6a885bb83c/round3_resources/followup_lm \
  --qualification /workspace/scratch/3f6a885bb83c/round3_resources/json-adapter-qualification-v1 \
  --pilot /workspace/scratch/3f6a885bb83c/round3_resources/json-adapter-pilot-v1 \
  --anchor remote-anchor.json \
  --runner-python /opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python \
  --output audit-reproduction.json
```

The runner source is not imported by the auditor, and its decoder is reconstructed
from the declared contract. All model/tool subprocess launches are forbidden
during receipt evaluation. The audit also checks that four earlier raw runs remain
unchanged; it only hashes those earlier files and does not parse or rescore their
model outputs. A new worker-failure receipt type causes an explicit audit failure
requiring review; it is never silently omitted or counted as success.

The result is limited to this actual execution: one qualification, 16 fixed task
episodes, 19 task model responses, four SQL calls and four exact-verifier calls.
It does not qualify new environments, inputs, transport errors, tools or models.
