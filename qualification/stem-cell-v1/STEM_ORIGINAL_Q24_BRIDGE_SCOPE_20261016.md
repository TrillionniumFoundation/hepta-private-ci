# Original Q24 bridge (research-only / DENY_ALL)

Parent lineage: PR #1825, exact frozen head `758205d3de23ccbf76649b1446c271101dc917b0`.

## Scientific gap
Existing real ModernBERT + BANKING77 shared Encoder evidence cannot be pooled with synthetic 32D Q24 Cell results from PRs #2426/#2462. This branch is for a real source-first TRAIN-only 32D projection and model-free independent numerical review.

## Original frozen source
- ModernBERT: `answerdotai/ModernBERT-base@8949b909ec900327062f0ebf497f51aef5e6f0c8`.
- BANKING77: `57ec275d8078af65b7731c2a98be812d844a6d6b`; four intents, 64 FIT and 32 official HELD.
- Encoder material/tensor checks and dataset material checks remain owned by original #1825 source.
- Consumer Q24 numerical format: signed Q24 32D bounded to [-8,8].
- FIT-only PCA mean, axes, scale; no HELD labels used before prediction seal.
- Original task-specific Head training, frozen and wrong-label controls; independent NumPy replay.
- No private raw texts, feature matrices, original model weights or HELD labels in public commits/artifacts.

## Nonclaims and promotion denial
Source/adversarial tests are synthetic and can only qualify local computation. Real pretrained CPU forward, independent source/issuer provenance, native Rust Q24 execution, prospective capability gain, multimodal generation, 421M comparison, NDU utility, Cell Split and production FinalUse remain independently gated. No CI result is claimed until observed. Never merge this branch to main or enable effects from a source-only pass.

Exact integration posture: DRAFT / SHADOW_ONLY / DENY_ALL / NO_FINALUSE.
