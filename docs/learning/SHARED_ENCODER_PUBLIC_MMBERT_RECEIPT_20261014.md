# Public mmBERT-small shared-Stem study: audited research receipt (2026-10-14)

**Not a deployed Hepta E0 baseline, not a future-window E1 comparison, no NDU promotion.**

## Source identity and immutable research evidence

- GitHub Actions run: [Hepta shared Stem actual execution, #38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991)
- Exact research source commit: `4133d6ac5bd3f8d4200c56fffb09e6aba004a084`
- Workflow status: completed/success for `public-pretrained-smoke`, `public-image-text` and `mechanics-and-browser`; this does not certify production readiness
- Archive: [hepta-public-pretrained-38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991/artifacts/11890616195), ID `11890616195`
- Uploaded and locally recomputed archive ZIP SHA-256: `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`
- Actual Encoder model ID: `jhu-clsp/mmBERT-small`
- Publisher revision: `abc32620dd4f6ab06f5fbe905dc25f310618e09f`
- Original downloaded `pytorch_model.bin` SHA-256 as claimed in `model-source.json`: `be7c9ce2af947fb5bb17a3bc919552f898c5ef4164bf0a7190cf25a0f98f85b6`; **the original weights are not in the archived study ZIP, so that hash was not independently recomputed from the archive**

## Exact study constraints

Public `fancyzhx/ag_news` dataset, pinned revision
`eb185aade064a813bc0b7f42de02595523103ca4`. The archive contains 64
training, 32 calibration and 32 Holdout records, with four output classes.
Two logical Cell Heads consume 384-dimensional features. Model loading and
forward passes used PyTorch CPU; the report records **128 encoded requests
across 16 actual batched Encoder forward calls**, not 128 separate forwards.

From archived `execution/predictions.json` and `dataset.jsonl`, the
following scores were **recomputed from individual probabilities and original
labels**, rather than merely copied from the publisher report:

| Head arm | Correct / 32 | Holdout accuracy | Multiclass Brier |
| --- | ---: | ---: | ---: |
| Gated | 22 / 32 | 68.75% | 0.5925344006794847 |
| Linear | 18 / 32 | 56.25% | 0.6243880673831524 |
| Low-rank | 21 / 32 | 65.625% | 0.5013715819763659 |
| Sparse expert | 13 / 32 | 40.625% | 0.8909663935166834 |

## Counterfactual screen: public parent_no_change is still stronger

The same archive has an **internal research** `parent_no_change` control
in `execution/controls.json`. After joining its ordered
`holdout_case_ids` against the original dataset, we independently
recomputed **26/32 correct (81.25%), multiclass Brier 0.3142704408**.

Paired against that specific local control, the four Head arms show:

| Head | Accuracy difference | Corrected errors (gains) | New errors (losses) | Brier difference (Head minus control) |
| --- | ---: | ---: | ---: | ---: |
| Gated | -12.50 pp | 2 | 6 | +0.2783 |
| Linear | -25.00 pp | 1 | 9 | +0.3101 |
| Low-rank | -15.625 pp | 2 | 7 | +0.1871 |
| Sparse expert | -40.625 pp | 1 | 14 | +0.5767 |

The positive Brier differences mean worse scoring than this local
control. This is **not** a matched-compute causal conclusion, and the
internal `parent_no_change` is *not* independently authenticated as
the actual deployed Hepta no-change model. Still, the source-observed
negative deltas must not be omitted when discussing the best shared
Stem/Cell architecture. The research data do not support promoting
any of these four Heads over the local parent control.

The ZIP archive matches the following report bindings:

- Dataset SHA-256: `50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c`
- Manifest SHA-256: `ad9312a0c981b27468d572a4f6c28d453e320c52dfd31261f9d7617d06639b4a`
- Predictions SHA-256: `88c9bb484f7e178686a4314f3c234bc6f4fd080057b0a5e80abcb785bc03edb9`
- Controls SHA-256: `aaff555316e9aaa9a3de6b51e7b506164663c55c58e0193d2b7156aa12f7506d`
- Head-batch SHA-256: `a01718d7a003ddb901abcaa4ebef9a25c08fe4a338198b5826f5780c43d81bc4`
- Frozen-feature safetensors SHA-256: `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`

Research process **lifetime** high-water RSS reported:
`2,677,153,792` bytes. It includes interpreter/runtime/model/Head operations
and is **not isolated Encoder RSS**, not an inference p99 latency, and not a
production host memory envelope. Active FLOPs, energy and GPU peak are null.

## Reproduce the read-only evidence audit

Download the exact archive from GitHub Actions and run:

```sh
python3 scripts/hepta-stem-public-artifact-audit.py \
  --zip hepta-public-pretrained-38546717991.zip \
  --zip-sha256 0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7 \
  --model jhu-clsp/mmBERT-small \
  --revision abc32620dd4f6ab06f5fbe905dc25f310618e09f \
  --out ./public-mmbert-research-audit.json
python3 -m unittest discover -s scripts/tests -p 'test_hepta_stem_public_artifact_audit.py' -v
```

The result **must** stay `PUBLIC_RESEARCH_ARCHIVE_SELF_CONSISTENT_NOT_E0`
with `DENY_ALL`. SHA matching and score recomputation prove only internal
archive consistency. This tool does not independently validate the GitHub
runner, publisher signature, downloaded original weight bytes, actual Hepta
deployment, Source Owner provenance, strict prediction precommit, independent
source-group identity or future NDU.

## Open hard blockers

1. Real deployed 421M/Laya/no-change model inventory and authenticated Worker receipts
2. Same-data, same-compute Granite 97M R2 and ModernBERT controls plus real Laya teacher policy
3. Prospective grouped and independently sealed predictions, independent NDU and old-task negative transfer
4. Physical Worker final-use/scope/lease/revocation/fence enforcement and audited CAS/CNS migration
5. Target-host CPU/GPU/RSS/p95/p99/energy and 64–4096 Cell recovery qualification

The completed public run reports
`independent_evaluation=false`, `production_accepted=false`,
`laya_comparison_completed=false`, `six_experiments_completed=false`.
Neither this document nor the verifier grants production selection authority.
