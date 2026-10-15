# MemoryCell real native model answer effects — 2026-10-15

**Research only. Do not promote production or infer parameter-learning superiority.**

This independent read-only audit examines the **exact original** GitHub Actions
[run #38675845950](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38675845950),
generating source `2b33c6321f52711761ec626ead27c9482c7c1cb0`.

## Original evidence and results

| Archive | Immutable Actions artifact | ZIP SHA-256 | Internally verified files |
| --- | ---: | --- | ---: |
| LoCoMo | `11946307808` | `310e38cfe87ae55838afb8612fb90eb028fc7abde55c529faa1d807fa878f333` | 101 |
| LongMemEval | `11946513138` | `95d1b57cab057e7fb5c45d9ba994c4b9d22d49f6e834abe7a0a7b2cc6106c315` | 98 |

**128 original successful pretrained model calls**: 16 questions × 4 arms × 2
published benchmark slices. All 199 SHA256SUMS members, original report JSON,
original arm-specific answer journals, question IDs, source family identity,
reader/encoder/source commit, and paired input/retrieval/evidence receipts
are independently reopened. No original answer is rewritten or regenerated.

### Paired answer census, not just rounded F1

| Benchmark | Comparison | Same original answer | Changed original answers | Scored F1 pairs | Unscored pairs | F1 wins/losses/ties |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| LoCoMo | no memory → parameter only | 16/16 | 0 | 12 | 4 | 0/0/12 |
| LoCoMo | RAG → RAG+LoRA | 16/16 | 0 | 12 | 4 | 0/0/12 |
| LongMemEval | no memory → parameter only | 16/16 | 0 | 16 | 0 | 0/0/16 |
| LongMemEval | RAG → RAG+LoRA | 15/16 | 1 | 16 | 0 | 0/0/16 |

All **64 parameter contrast pairs** use byte-identical original input
Token-ID SHA, selected retrieval identities and delivered evidence lists.
**63 original answer strings are byte-for-byte identical**. The sole
RAG+LoRA answer change on `longmemeval:b5ef892d` had diagnostic F1 **0 → 0**.
Consequently **none of the 56 scored parameter pairs improved or worsened
F1**, while **8 unscored pairs stay missing**, not fabricated zeros.

The separate no-memory → RAG control is **not** a same-evidence parameter
contrast. Across 28 scored paired questions it has 7 F1 wins, 10 losses,
11 ties (and four additional unscored LoCoMo questions). Evidence changes
under retrieval, so causality cannot be attributed to training.

The two published slices yield **three source-family digest proxies** (two
LoCoMo histories, one LongMemEval family). These are not independently
authenticated effective `N>=200`, prospective families, accepted reviewer
entailment or real future-window tests. Reader call seconds are partial
query measurements, not full amortized storage/training/revocation/recovery
cost. This study does not re-execute inference or inspect deployed hosts.

## Reproduce exactly on immutable originals

```bash
PYTHONPATH=scripts/memory_cell \
MEMORY_NATIVE_LOCOMO_ZIP=LOCOMO_ORIGINAL.zip \
MEMORY_NATIVE_LONGMEMEVAL_ZIP=LONGMEMEVAL_ORIGINAL.zip \
python3 -m unittest discover -s scripts/memory_cell \
  -p test_memory_parametric_behavior_audit.py -v

python3 scripts/memory_cell/memory_parametric_behavior_audit.py \
  --locomo LOCOMO_ORIGINAL.zip \
  --longmemeval LONGMEMEVAL_ORIGINAL.zip \
  --output NEW_IMMUTABLE_REPORT.json
```

Workflow `.github/workflows/hepta-memory-native-parametric-behavior.yml`
re-downloads two original immutable ZIPs and retains only the new aggregate
and changed-answer digests — no model weights, private keys or raw human
answers. This is not the separate pending **v3 72-call Git-source Reader**,
its source-rank paired scorer, or the **v4 36-call source-order** intervention.
Keep those distinct. `semantic_citation_entailment_certified=false`,
`independent_future_population_qualified=false`,
`full_lifecycle_tco=null`, `production_qualified=false`.
