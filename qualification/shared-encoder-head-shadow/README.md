# Real public Q24 features → Cell-specific Head shadow

**RESEARCH ONLY · DENY_ALL · NO PRODUCTION PROMOTION.** Attached to [PR #2591](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2591). This is not a production Agentd source, an independent signed Final-use receipt, a model artifact CAS or a measured NDU gain.

## Frozen source

- Pretrained public **ModernBERT-base**, revision **8949b909ec900327062f0ebf497f51aef5e6f0c8**.
- Public **BANKING77** dataset revision **57ec275d8078af65b7731c2a98be812d844a6d6b**.
- Source [Actions run #38902031341](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38902031341) completed successfully; artifact **12068510329**, name **stem-real-public-q24-feature-snapshot**.
- Exact ZIP SHA-256: **dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a**.
- Exact SEALED.json SHA-256: **180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2**.

The upstream producer attests **96 actual Encoder forward calls**, 768D pooled pretrained features and train-only 32D PCA/Q24 vectors. The present study **reuses archived tensors**; it does NOT rerun ModernBERT, sign weights, or prove a production feature owner. Both pinned hashes and the previous independent reopen verdict are verified. A checksum is not an authenticated provenance signature.

## Fixed experiment

The [shadow runner](real_public_q24_shadow.py) validates exact ZIP members, their bytes and SHA-256 values, model and dataset revisions, 64 fitting labels, 32 official-test examples **without labels**, tensor shapes, and all no-promotion markers.

Four-fold stratified validation partitions **only the 64 fit examples**. Each fold independently computes PCA32 from the 48 training-only pooled pretrained features, applies it to 16 previously excluded examples without reading their labels, and trains for **120 AdamW steps** with identical fixed optimizer settings.

- Random frozen initial four-linear-Head is an experimental ablation, **not production no-change**.
- Trained linear: four independent 32→1 Heads, **132** total parameters.
- Trained gated rank-4: four 32→4→32 residual/sigmoid-gate Heads, **1,288** total parameters.

The fold-specific PCA outputs are newly derived research views, not the previously sealed original Q24 Snapshot. In a separate full-fit pass, each model trains on the **original saved Q24 fit matrix** and emits unscored predictions for the **32 official heldout inputs**, without seeing heldout labels. Only hashes of the F32 probability arrays are stored in [one-seed evidence](REAL_PUBLIC_Q24_ONE_SEED.json).

## Actual outcomes

| Model | One-seed accuracy | Five-seed mean accuracy | Five-seed mean log-loss |
| --- | ---: | ---: | ---: |
| Frozen random Heads | 29.6875% | 24.0625% | 1.462835 |
| Trained linear Heads | 87.5% | **90.625%** | **0.322967** |
| Trained gated rank-4 Heads | 89.0625% | 88.4375% | 0.334231 |

Five seeds: **17, 23, 41, 59, 73**, reported individually in [five-seed evidence](REAL_PUBLIC_Q24_FIVE_SEED.json). They reshuffle the **same 64 fit examples** and are neither five independent datasets nor a future-time task study. Gated uses around 9.8× more parameters and did **not** improve the multi-seed averages here. Training optimizer byte counts are tensor payload only; no full system RSS or GPU allocation is measured.

## Reproduce with the physical artifact

Download the archived ZIP from Actions artifact **12068510329**, preserving its original bytes, to this directory as **stem-real-public-q24-feature-snapshot.zip**. Verify its exact ZIP SHA above before use. With Python, NumPy 2.3.5, Torch 2.10.0+cpu, and safetensors 0.7.0 installed, execute:

    cd qualification/shared-encoder-head-shadow
    python real_public_q24_shadow.py --snapshot stem-real-public-q24-feature-snapshot.zip --output shadow-rerun.json
    python -m unittest -v test_real_public_q24_shadow

The runner refuses to overwrite an existing result. To reproduce the panel, import **run** from the script and invoke it for the five declared seeds; take the arithmetic mean of the returned four-fold metrics. The current local study passed four positive/negative controls, including fabricated heldout labels, forged source authority and corrupted safetensors. This does not establish the Rust PR CI status.

## Remaining acceptance gates

1. Obtain real Rust formatting, test, strict Clippy, and scoped architecture CI receipts for the exact PR head.
2. Pin and run true pretrained Encoder/tokenizer/normalizer weights within a production-owned Worker, not a caller-supplied digest or a cached research tensor.
3. Enforce independent authenticated source/currentness and signed Final-use at physical dispatch; use Artifact CAS, generation fencing and owner reconciliation.
4. Integrate real feature projection and Cell Head tensor execution with the registered Rust inference/Neuron ports.
5. Compare total serving/training/evaluation budget against actual shared Laya/no-change and evaluate group-independent future outcomes, NDU, negative transfer, and 64/256/1024/4096 target-host resource profiles.

**No production promotion, main merge, CNS cutover, or Cell Split is authorized by this research evidence.**
