# V14 — Fixes from actual hosted CI failure logs (research / NO-GO)

Exact failing source: \`30c36096aa713e3d7098a79c2f080dff2900b684\`.

- V7 job 116188903826: safetensors import failed for missing packaging.
- V6 job 116188905343: same missing packaging.
- Multimodal job 116188904272: cryptography, psutil, NumPy and
  other dependencies absent from isolated testing environment.
- V5 job 116188904357: actual random-BERT prediction failed in
  torch.embedding with index out of range. Model fixture allocated
  17 embedding rows; vocabulary contains 18 entries. Its TRAIN examples
  never referenced the last index; FUTURE examples did.

V14 explicitly installs missing pinned dependencies and requires
import preflights for affected isolated runners. The V5 fixture now
allocates 18 embeddings and checks tokenizer length. A new negative
physical test adds a 19th token to an unchanged stock checkpoint and
requires LocalEncoder admission failure before training or inference.
LocalEncoder also verifies every tokenizer token ID is within the
already byte-verified model embedding range; no weight resizing,
silent truncation, fallback or substitution is permitted. The V5 CI
requires all 3 physical tests without skips.

CI checks must run anew on the exact amended commit. A green contract
does not certify real pretrained mmBERT/Granite quality, matched training,
future NDU benefit, Rust data-plane performance or production authority.

## Follow-up: mmBERT historical safetensors physical load

The pinned public mmBERT-small weights passed source and transfer hashing in
hosted push run 38663153113, but the HF loader failed with
`NotImplementedError: Cannot copy out of meta tensor; no data!`. That is not
proof of low model quality. We now check parameter AND buffer materialization
before `.cpu()` and emit bounded missing/meta tensor names. This diagnostic
**does not** initialize missing tensors, call `to_empty`, convert `.bin`, or
relax the saved-weight verification. The next physical run must identify exact
unmaterialized names before any possible targeted compatibility fix. Granite
had successful frozen forwards in the same original run. Pair promotion stays
blocked until both physical arms finish with authentic material.

## V15 bounded dense CPU load experiment

After pinning the approved mmBERT-small safetensors revision, hosted
physical run 38664390199 reported exactly two unresolved Meta views:
`model.embeddings.tok_embeddings.weight` and `decoder.weight`, with
zero loader-reported missing keys. This is not a passing pretrained forward.
The stock ModernBERT MLM CPU/eager loader now requests
`low_cpu_mem_usage=False` under the already reviewed Transformers 4.57.1
runtime. It is not a model downgrade, new checkpoint or a silent parameter
initialization policy: the subsequent independent `require_materialized`,
strict safetensors-to-loaded-tensor byte equality, only physically verified
tied alias, and post-forward original-file hashes remain mandatory. If
anything is still missing, randomly initialized or alias-mismatched,
execution must fail closed. This experimental loader option may increase
peak CPU memory and is NOT accepted as production memory evidence.
