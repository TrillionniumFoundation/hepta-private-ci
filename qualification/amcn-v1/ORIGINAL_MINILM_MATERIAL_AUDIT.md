# Original LoCoMo + MiniLM typed MemoryCell material audit

**Status:** original locally available historical bytes audited on 2026-10-14.
**Claim:** SHADOW / NO-GO. No product use, independent data-source signatures,
verified HF AutoTokenizer/AutoModel parity, new Reader generation or calendar future.
This document is an original-byte diagnostic, **not hosted GitHub Actions output**.

## Exactly pinned original material

- Original 376 MB compressed archive from original GitHub Actions artifact
  `11586991191`, ZIP SHA256
  `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
- Original LoCoMo JSON SHA256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`;
  only **10 original conversation families**.
- Archived original MiniLM encoder `model.safetensors` SHA256
  `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`.
- Frozen label-blind original source-first candidate plan
  `ec478977b3f1e5b5b1e654a946df7acb405239745be6f4b4e84a82a6dc848f46`.
- Original locally generated physical-feature tensor:
  1,472 × 384 float32 (2,260,992 payload bytes), file SHA256
  `33342df20c3d6348e32e4ff782bce9a269ec2dfbdb7ddb0611b7b46de67df11a`.
  Custom PyTorch MiniLM BERT math / WordPiece over original archived weights;
  **neither HF tokenizer nor HF operator parity is verified**.
- Six actually trained or frozen gated Head safetensors; all six original
  19,040-byte model files hash-verified (114,240 bytes total), each
  4,636 FP32 parameters. Paired typed/untyped budget: 9,272 parameters.
  Bank manifest raw SHA256
  `fc44ddf3dead1b24bee7be5b170f5b8b0a53960842a98475a4f55fe3188c3fe1`.
- Original 704 non-TRAIN prediction rows digest
  `d5634967afb37285f95f7458e210696ed0d9e5c61ee6c31017a1e8d08042379d`.
  Both original physical Head readback and independent source-first
  44-question scoring have separate receipts; this audit checks their
  exact original bindings but does not reexecute the original Encoder.

## Descriptive original publisher-weak evidence Hit@1

| Historical split | Questions | Lexical Top-1 | Unspecialized equal budget | Typed equal budget |
| --- | ---: | ---: | ---: | ---: |
| SELECT | 16 | 4 | 0 | 2 |
| FUTURE_A | 8 | 2 | 1 | 0 |
| FUTURE_B | 8 | 3 | 1 | 1 |
| RETENTION | 12 | 5 | 0 | 1 |
| **Total** | **44** | **14** | **2** | **4** |

Fifteen of 44 questions have **zero** publisher-weak support in the
source-first final Top-16; all 15 remain in the denominator. Any Head can
only rerank that fixed frontier, not reconstruct absent citations. The typed
Head's two extra hits over the unspecialized control do **not** establish
an improvement over lexical retrieval: typed is 10 hits below lexical.
FUTURE_A and FUTURE_B are **retrospective splits of two source families**,
not observed future calendar windows. On these two families the type-vs-
untyped paired win/loss/tie is 0/1/1. Row-level accuracy is not task success.

## How to independently rerun the bounded physical *material* audit

Stage the original ZIP, JSON, original Encoder safetensors and vocab, original
feature safetensors and manifest, sealed Head predictions, six original
Head safetensors plus manifest, and question-level evaluation JSON. Obtain
the original bytes from the immutable source or operator-controlled archive.
Never substitute a model-card claim or a newly generated blob for pinned bytes.

```python
from amcn_typed_physical_audit import audit_local_materials
result = audit_local_materials(
    archive_zip, original_locomo_json, encoder_weights, original_vocab,
    feature_safetensors, feature_manifest, original_predictions_seal,
    saved_head_bank_directory, original_question_score_json,
)
assert result["production_accepted"] is False
```

`amcn_typed_physical_audit.py` physically rehashes the source ZIP,
original corpus, Encoder safetensors/vocab, feature safetensors, six
Head safetensors and manifest; recomputes the complete original prediction
digest and exact 48 (4 splits × 2 types × 6 arms) question-result strata.
It fails on swapped model/source, missing Head, changed prediction, forged
reader/HF parity claim, wrong original split, or changed source-first recall
ceiling. The **hosted isolated workflow only executes contract tests**, not
a 376 MB hosted archive rerun. No user payloads, source messages, private
label files or model weights are committed by this PR.

## Acceptance is still blocked

Missing authentic HF tokenizer/model forward parity, independent qualified
issuer/source references, stronger Reader question-answer results and
citation judgment, full strong hybrid RAG, independently measured compression
and lifecycle costs, three independent snapshots, two genuine prospective
calendar windows, >=200 effective independent families, source withdrawal
and true parameter-unlearning/retrain, signed NDU selection, durable CNS
cutover/rollback, and exact-head `blocking-ci`.
