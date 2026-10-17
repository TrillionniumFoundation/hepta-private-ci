# V2 exact original-model evidence and negative qualification

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. No main merge, selected Stem, Cell Split, NDU or FinalUse.**

Physical historical original [Actions #38989271689](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38989271689) completed all six jobs on immutable source `2fc6a8d9ed331a78827281eee360c5a8d47fa1d2`: source owner, three independently run real pretrained CPU Encoder/Head producers, and late-label original BANKING77 publisher independent reviewer. Original ZIPs and inner JSONs are individually SHA-256 frozen in `original_receipt_audit_v2.py`. The PR-triggered [#38989300128](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38989300128) did **not** re-run physical models; it skipped producers/reviewer, despite total workflow success.

| Model | Learned / 32 | Train-class centroid / 32 | Frozen / 32 | Original learned Brier | Self-reported peak RSS | Self-reported feature forward wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Granite 47M | 32 | 32 | 8 | 0.003268 | 685,789,184 bytes | 0.898 s |
| Granite 97M | 32 | 32 | 7 | 0.000751 | 1,178,001,408 bytes | 1.046 s |
| mmBERT-small | 20 | 18 | 8 | 0.661340 | 1,195,044,864 bytes | 1.698 s |

Exactly 64 TRAIN / 32 heldout original samples, four BANKING77 intents, 384D forced masked-mean/L2 features, four independent 6,914-scalar Heads, 100 optimizer steps, 96 real pretrained Encoder sequences and six batches **per model**. These are actual Actions process observations, not an accredited device p99/energy or issuer signature.

V2 is a *second immutable artifact-custody audit*: it opens four exact original complete ZIP bytes (not a caller-supplied digest), independently checks input/model/Head identity, case coverage and all output probability distributions, and compares class predictions **without gold**. Granite 47M vs 97M disagree on 0/32 predicted classes under either learned or centroid head. Each Granite learned prediction differs from mmBERT on 12/32. Accuracy/Brier figures are from the ORIGINAL independent publisher reviewer, **not a new independent label read in V2**.

**Critical no-go:** both Granite trained Heads are 32/32, **and both cheap supervised TRAIN-centroid baselines are 32/32**. Thus no incremental *correctness* above this cheap comparator has been established. Their lower retrospective Brier does not prove new-source calibration, old-task retention, causal NDU gain, broader intelligence or equal-resource lifecycle advantage. This cohort is one small original public source family with zero prospective future windows. Different GitHub runner resource observations are descriptive only.

Outstanding strict gates: original 421M shared/replicated comparison; per-model official pooling vs forced mean; genuinely source- and time-disjoint tasks; production no-change and cheap matched-work controls; authenticated old/new retention and real utility; final target-host 64/256/1024/4096 fleet CPU/RSS/GPU/p95/p99/energy/WAL/recovery. Global `blocking-ci` on original candidate currently fails Prettier (including V1 workflow and inherited YAML), cargo-deny advisories, Bazel/Clippy and Windows tests; no suppressions allowed. This V2 reread does not fix or bypass those independent blockers.

Reproduce from four original pinned Actions ZIP files:

```sh
python qualification/stem-optimal-v1/original_receipt_audit_v2.py \
  --granite47 granite47.zip --granite97 granite97.zip \
  --mmbert140 mmbert140.zip --review independent.zip \
  --output original-v2-custody.json
```

The output must remain `HOLD_NO_GO`, `DENY_ALL`, with `stem_winner_verified=false`.
