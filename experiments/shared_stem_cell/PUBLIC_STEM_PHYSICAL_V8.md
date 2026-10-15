# V8: public mmBERT-small + Granite 97M exact-source CPU canary

**Research-only; no production authorization, no model-selection result.**

The first non-synthetic task after native Pooling V7 is physical pretraining-material acquisition. Both candidates are **explicitly** cataloged and cannot be silently replaced:

| Arm | Publisher repository | Kind | Dim | Pooling / normalization |
| --- | --- | --- | --- | --- |
| mmbert-small | `jhu-clsp/mmBERT-small` | masked_lm | 384 | attention-mask-mean / none |
| granite-97m-r2 | `ibm-granite/granite-embedding-97m-multilingual-r2` | encoder | 384 | cls-first-token / unit_l2 |

Model-native mean for mmBERT is an experimental feature-extraction policy, **not** an independently proven optimum. Granite uses documented CLS and L2 policy. Same 384-dimensional interface does not imply equal quality or task suitability.

The `prepare` process now requests two **explicit immutable source revisions**:
`jhu-clsp/mmBERT-small@0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`
(published `model.safetensors` release) and
`ibm-granite/granite-embedding-97m-multilingual-r2@835ad14087e140460703cf0fae09f97d469d65c2`
(the revision with a successful hosted forward receipt). The default mmBERT
`main` is currently bin-only and is *not* an admissible source. No automatic
unsafe pickle load, weight conversion, alternative model, or moving-tag fallback
is allowed. The Hub result must match each registered full commit before
the first weight transfer. A plan records only permitted metadata and safetensors weights with sizes and optional Hub LFS SHA-256. `run` refuses moving refs, mismatched repository/revision or file inventory, unlisted paths, duplicate manifests, unbounded sizes, missing shards, or mismatched downloaded bytes. A local metadata pin is **not** a publisher signature or independent operator admission.

The physical canary uses `execution.LocalEncoder` (the same strict stock HF safetensors verifier as prior V7, not an invented loader). It loads frozen weights and tokenizer from the complete inventory, performs two independent batches with each candidate's frozen pooling, validates `[2,384]` finite CPU features, exact same-input repeatability, differing input signals, two counted physical forwards, and post-forward rehash of all files. It reports honest measured wall/CPU time and **process-lifetime**, not per-call, peak RSS; missing GPU/energy/FLOP measurements are not imputed. Incompatible mmBERT model loading and missing dependencies fail closed with a diagnostic rather than relabeling a random or different model as mmBERT.

`prepare` and `run` require public Hub network access. They are a controlled public research acquisition; only the network-free 12 contract tests ran locally. The GitHub workflow has a separate CPU test job and a push-only physical job. `if: always()` evidence upload explicitly excludes weights and tokenizer material; neither a passing fake fixture nor a public weight canary confers model origin attestation or calibrated learning evidence.

```bash
python -m unittest discover -s experiments/shared_stem_cell -p test_public_stem_material_v8.py -v
# Requires installed pinned Torch/Transformers/HF stack and real external network access:
python experiments/shared_stem_cell/public_stem_material_v8.py prepare --candidate mmbert-small --out /tmp/mmbert.plan.json
python experiments/shared_stem_cell/public_stem_material_v8.py run --plan /tmp/mmbert.plan.json --output /tmp/mmbert-result
```

**Unclosed gates:** actual hosted CI success; two exact-source genuine pretrained physical receipts; shared hardware and dataset same-budget training; independently sealed future labels and no-change baseline; multimodal image/audio features; Rust physical sharing and final-use; NDU selection, recovery and target-host 64/256/1024/4096 Cell measurements. `production_accepted=false` and `authority=DENY_ALL` remain enforced.
