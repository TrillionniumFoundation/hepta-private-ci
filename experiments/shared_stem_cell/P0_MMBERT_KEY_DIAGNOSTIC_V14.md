# P0 V14 original mmBERT state-key diagnostic — research only

The observed `mmbert_small` native-MLM failure in V13 is
`non-tied pretrained MLM parameter initialized randomly` from the original
pinned `e1_mmbert_tied_loader.py`. The strict physical-loader decision remains
correctly **DENY_ALL** until the model's source weights are fully matched.
A general error phrase cannot establish which checkpoint key was missing.

This additive read-only lane uses the exact original model revision
`0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` and the existing SHA/LFS
source preflight. It replays the same pinned 5.19.0 Transformers loader and
records only bounded model tensor NAMES: missing, unexpected, mismatched,
loaded-state-only and source-only. It never emits tensor bytes, prompts,
original human labels, model weights or private transport error strings.

The resulting JSON is an **explanatory diagnostic**, not a source signature,
load success, reader success, cross-model comparison, model selection or FinalUse.
The original `FrozenMMBert` full tied-table and every-tensor comparisons remain
unchanged, including refusal of non-tied missing weights. No synthetic substitute
or newer unpinned revision is allowed. The genuine physical inference job must
still be repeated and independently adjudicated on its exact future HEAD.

Hosted `.github/workflows/hepta-p0-mmbert-key-diagnostic-v14.yml` invokes both
source and prospective merge variants and retains a diagnostic-only artifact.
Any pinned-source acquisition or diagnostics failure remains a failure.

Model-free local regression:

```
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover -s experiments/shared_stem_cell -p test_p0_mmbert_mapping_diagnostic_v14.py -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover -s experiments/shared_stem_cell -p test_p0_mmbert_mapping_diagnostic_v14.py -v
```

This is off-dot, research-only evidence. No production activation or main merge.
