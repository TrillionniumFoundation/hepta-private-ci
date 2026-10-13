# Verify the archived BERT nonpersistent position buffer, not an ignored key

Date: 2026-10-13. PR #1697; parent `d78da3aee399d016b3ea6b18e2aa036fb653d6f6`.

## Actual diagnosis before changing acceptance

Focused run **38423208299**, job **115385685503**, executed the original pinned
model archive on exact source `d78da3a...`. The audit found **104 saved tensors,
103 loaded state_dict tensors, 2 named buffers**, and no loaded state key absent
from the archive. All 103 saved parameter/state tensors had the expected shapes
and exactly equal loaded values. HF reported no missing, unexpected, mismatched
or error keys. The SOLE saved key absent from state_dict was
`embeddings.position_ids`, dtype int64, shape **[1,512]**. It matched the actual
loaded buffer exactly, including dtype, and was exactly `arange(512)`.
The then-unchanged strict loader still failed, as expected. The diagnostic run
was FAILURE, not a waiver of material verification.

Artifact **11828050823**, GitHub-reported **19,569 bytes / 10 files**, SHA256
`1535c496b20aa66cbf3f62ef587fea9770cc1ba7892a3f089e3531757a7241e6`.
No local artifact rehash is claimed. The independent PyTorch arithmetic reference
was NOT substituted for the official loader.

## Narrow material verification correction

HF 4.57.1 BertEmbeddings registers position_ids as persistent=False. state_dict
therefore cannot enumerate this runtime buffer, even though the historical
checkpoint serialized it. LocalEncoder now verifies this one explicitly observed
legacy entry against BOTH the loaded nonpersistent buffer and the deterministic
zero-based positions required by its configuration. Shape, dtype, actual model
class and persistence status must match. Noncanonical values are rejected even
when the saved and loaded buffers agree with one another. Verification never
rewrites a buffer or strips a file from the immutable snapshot.

This rule is restricted to **exact stock BertModel / embeddings.position_ids**.
It does not admit arbitrary buffers, renamed namespaces, missing learned weights,
extra classification/decision Heads or remote model code. Other model classes
and prefix variants remain unsupported rather than guessed. Every state tensor
still undergoes the same materialized-value verification; tied aliases still
require actual verified storage. Duplicate saved keys remain rejected across
files. Original archive, config, tokenizer, file inventories and parameter bytes
are unchanged. The backend retains a verified_legacy_buffers record with the
actual saved/materialized tensor digest and explicit profile
`bert-nonpersistent-position-equality-v1`.

Seventeen new fixture tests cover modern and legacy saves, original-model forward
comparison, wrong saved values/dtype/shape, unrecognized buffers, duplicates,
missing learned weights, extra learned Heads, jointly shifted positions, live
buffer mutation, wrong model class, persistence, missing buffer, configured
capacity and changed file pins. Tiny random fixture weights are not a model
capability claim. The native workflow keeps all previous suites and requires the
new suite before executing historical models. The focused original-material
probe is separately rerun by this source change. No new source test or patched
model result is assumed before those exact-source jobs finish.

## Relationship to Reader learning

This only repairs original Encoder material loading, which blocked the final
legacy Head smoke AFTER the already completed Reader study. It does not change
Reader training data, objective, seed, LoRA, answer masks, scoring or candidate
selection. The observed unconditional-refusal result remains frozen in
FIVE_READER_FIRST_TRAINED_RESULT.md. Repeating the full workflow pays its training
and replay cost again and is replication, not additional independent task data.
No candidate is adopted and no formal Reader/Group/multimodal gate is opened.

Primary code definition:
https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/bert/modeling_bert.py
