# HDCF V8 — Original shared Stem / Cell differentiation negative control

**Disposition: DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO.**

## What was actually run

Reopened **four exact immutable original GitHub Actions ZIPs** from [run 38930339541](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38930339541), produced on the unchanged V6 source commit `b89a0b4a32eaa92881a79140256079aed0c38fe4`:

| Original artifact | Artifact ID | Outer ZIP SHA-256 |
|---|---:|---|
| Frozen 768D ModernBERT features | 12083071509 | `3d8d6b7bed80f1f5efb1a17fd1df94208bef4239e5bbbbcd29e63262fb6e025d` |
| Five-arm real CPU Head experiment | 12083091720 | `8bd2d2ba3b2de9f2fe1b99042b471c016d78f90c8305d7d82c91bf1a23138bed` |
| Blind target owner | 12080419743 | `140191b7915923b51a447c9cabc43d6dbba96060ae4dee90716f1fd2539821fb` |
| Original public case identities | 12080649303 | `51e258a7a721a03f402e6606cffb57f52e5ee35a458f5f75218eaafabd9fe698` |

Original source: pinned BANKING77 public four-intent subset, 64 fitting and 32 historical test records from the same dataset publisher, binary label = original four-class label mod 2; pretrained frozen Encoder performed **96 original forwards**. The Cell `hash0/hash1` router is SHA-256 parity of a source case identity, **not a learned semantic task type**. Its two types have the following **fitting-only** label counts:

| Type | Target 0 | Target 1 | Laplace(1) `p(target=1)` |
|---|---:|---:|---:|
| hash0 | 15 | 20 | 21/37 = 0.5675676 |
| hash1 | 17 | 12 | 13/31 = 0.4193548 |

The independently replayed original Split Cell and the cheap route-only training-majority model make exactly **the same 32/32 binary decisions**, **20/32 correct** on the historical test. Inference with the actual independently rebuilt Split weights but all **768 Encoder feature coordinates replaced by zero** also makes **32/32 identical class decisions**. The feature ablation retains *type and the learned weights*; it does not prove the probabilities or all tasks are invariant to semantic features.

| Historical 32-case metric | Real Split | Train-only type prior (alpha=1) |
|---|---:|---:|
| Correct | 20 | 20 |
| Mean Brier (lower better) | 0.23901125 | **0.23725020** |
| Mean negative log likelihood (lower better) | 0.67108347 | **0.66750527** |
| Head scalar SGD updates | 256 | **0** |
| Requires 768D pretrained features to classify by original type-ID rule | yes | **no** |

**Interpretation:** The observed original Split Cell result does not demonstrate additional class-decision information from the pretrained Encoder beyond the cheaply recoverable type/label prior. The small Brier/NLL improvements are **retrospective descriptive** only; V8 was proposed after examining the V6 test results. Do not claim generalization, a pre-registered model superiority experiment or a statistically independent second sample.

This is not a model capacity theorem. Not all 768D representations, all downstream Readers, probability rankings or other tasks are unnecessary. A future run needs genuinely unseen publisher/task/time groups and predeclared no-feature/no-learning controls before any claim of semantic feature usage or benefit from Cell differentiation.

## Strict audit and reproduction

`type_prior_negative_v8.py` verifies the complete original outer ZIP digest **and each required member SHA-256**, parses bounded/strict JSON without extracting ZIPs, checks exact original model, source, public/held case IDs, original label parity, source ID-derived routing, 96 observed feature forwards, and replays all five original fitted Heads/160 predictions through the **existing independent Head replay**, not the producer's recorded accuracy alone. It then rebuilds the original Split Head weights independently and performs the zero-vector evaluation.

```sh
cd qualification/hdcf-research
python3 type_prior_negative_v8.py \
  --features-zip /private/original/frozen.zip \
  --trial-zip /private/original/trial.zip \
  --targets-zip /private/original/targets.zip \
  --public-zip /private/original/public.zip \
  --out /new/private/diagnostic.json

HDCF_V8_FEATURES_ZIP=/private/original/frozen.zip \
HDCF_V8_TRIAL_ZIP=/private/original/trial.zip \
HDCF_V8_TARGETS_ZIP=/private/original/targets.zip \
HDCF_V8_PUBLIC_ZIP=/private/original/public.zip \
python3 -m unittest -v test_type_prior_negative_v8
```

If original ZIPs are absent, original-only unit tests visibly **skip**; a fixture-only pass must never be represented as a real original replay. The dedicated source-head Actions workflow downloads only these four named, fixed-ID artifacts, refuses any ZIP SHA mismatch, requires no skipped original tests, and uploads **only a bounded diagnostic JSON** without raw features, labels, model tensors or authenticating signatures. No new model download, GPU run or costly pretrained Encoder forward is required.

## Authority and scientific boundaries

This package changes no inference Worker, selected model, NDU/utility owner, learning artifact selector, CNS/TaskFlow writer, FinalUse, signed native execution, executable memory, GPU driver or product CellSplit. The archived prior/head costs are not independently attested full lifecycle TCO; the *strict* 0-vs-256 additional Head SGD work is an algorithmic comparison only. ZIP hashes authenticate archival byte identity, **not their original publisher or hardware**. `HOLD_NO_GO` remains the only disposition. Separate security/cargo-deny, Prettier, Clippy, Bazel and Windows failures cannot be waived by success here.
