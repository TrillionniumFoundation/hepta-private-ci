# P0 V15 strict native mmBERT tied-alias loading report — DRAFT / DENY_ALL

## Parent and observed evidence

Frozen candidate parent: P0 #2378 `09e5d4806c166586ba18b2ac87f75034fecd6687`.
No changes to P0 original dataset selection, original Laya/Granite/Gemma,
authenticated source preflight, previous research receipts, production
Rust NDU/Worker/FinalUse/CAS/CNS or `main`.

Old P0 physical `mmbert_small` at V13 job `116745370539` failed the
`e1_mmbert_tied_loader.Invalid: non-tied pretrained MLM parameter initialized
randomly` loading-info guard. This failure is REAL but the generic exception
did not publish the specific missing aliases.

The independent V14 **actual pinned-model** names-only diagnostic at
run `38868208653`, source artifact `12038340980`, reported:
- 137 original safetensors names, 138 runtime state names
- 0 reported non-tied missing keys, 0 loading-info missing keys
- `model.embeddings.tok_embeddings.weight` is the runtime-only name while
  `decoder.weight` is serialized; they represent the tied vocabulary table.

These are not physical byte-comparison results, and the diagnostic result
does NOT prove why the older real P0 process reported missing keys.
Do not claim that accepting aliases definitely fixes that historical failure.

## Candidate source correction

The old `FrozenMMBert` guard refused ANY loading report with more than one
missing name, even if the only two entries were the already registered physical
tied table aliases. That count-based branch conflates missing generic learned
parameters with the same tied table being described twice.

`require_verified_alias_only_loading_info(info)` now:
- requires explicit well-typed missing-key lists and well-typed,
  EMPTY unexpected/mismatched/error lists;
- refuses duplicate keys, nonstring names, any third key, ANY non-tied key;
- provisionally recognizes ONLY `decoder.weight` and
  `model.embeddings.tok_embeddings.weight` (zero, one or both);
- is deliberately NOT a model acceptance operation.

Crucially, the original `verify_tied_pretrained_table` still requires the
two model tensors to be the **same physical view** and checks the entire
pretrained table against exact source safetensors, and the original
`verify_complete_pretrained_state` still byte-checks EVERY serialized tensor
and refuses any unsaved non-tied tensor. Both must pass after the report,
otherwise the loader raises and produces NO model features.

The original revision, tokenizer, 512-token cap, local-only safe weights,
whole-file preflight, independent human owner, no-truncation, CPU-only,
research `DENY_ALL` and all-four consensus requirements remain unchanged.

## Verification and remaining gates

New six model-free, source-only policy regression methods passed locally in
ordinary Python and `python -O`. A separate local synthetic Torch +
safetensors scenario verified that a valid alias name inventory cannot
substitute for checking the actual native weight bytes (4 physical/mechanism
tests ordinary and `-O`).

The existing `test_e1_mmbert_tied_loader.py` physical synthetic tests are
added to the exact-head diagnostic CI AFTER Torch/safetensors installation.
Two diagnostic modes (source & prospective merge) still run, retaining the
original immutable source/LFS acquisition and original names-only receipt.

**NO** successful original mmBERT inference, full four-model P0 score,
future utility, 4,096 Cell scalability, model selection, signed producer,
production FinalUse or physical Cell Split is asserted by local testing.
The existing P0 V13 run `38868208650` must finish; then this candidate
requires a new exact-source hosted run, independent original owner score and
separate global blocking/architecture CI. Neither missing nor queued evidence
is a success.

**DRAFT / RESEARCH / DENY_ALL. Do not merge main or promote a Stem.**
