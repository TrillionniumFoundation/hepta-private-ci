# E1→E2 frozen Q24 feature-bank lineage — read-only scientific gate

Research-only / `DENY_ALL` / no production effect. The previous E2 audit bound its output to an E1 report SHA and declared `existing_frozen_encoder_features_reused=true`, but did not bind **the per-case Encoder feature content that every E2 Head trained on**. This gap could hide E2-specific feature substitution and invalidate a Cell learning comparison.

## What changed in the real executable E1/E2 path

`e1e2_q24_identity.py` defines a stable, versioned digest over each **case ID and complete 256D or 384D rounded Q24 feature vector**. Every signed coordinate is encoded as little-endian 64-bit integer after Python ties-to-even `round(value × 2^24)`. The case digest contains an explicit width and domain-separated prefix. A separate SHA-256 hashes the complete sorted case-ID/digest inventory. The helper rejects invalid widths, missing/duplicate case IDs, nonfinite values, and values outside [-8,8].

- The **actual E1 real CPU runner** computes the inventory before fitting its 2K Head, asserts the frozen feature bank stays unchanged after optimizer work, and publishes the 224-entry inventory in the original create-only E1 result. It does not expose or upload raw embedding tensors.
- The **E2 real SGD study** computes the same inventory independently from its consumed frozen vectors *before* SGD, then recomputes it *after* its 2K/8K/16K residual/cosine/from-zero arms and rejects source mutation. It preserves existing same-process frozen-base weight sharing and unchanged original Head controls.
- The **independent E2 scorer** rejects any missing, substituted or reordered case inventory; independently recomputes both whole-bank digests from the claimed per-case digests and requires identical E1/E2 full bank content, shape and case coverage. A digest-only assertion without the complete case inventory fails closed.

These checks demonstrate exact *reported* source-to-Head **feature identity**, not an independently signed model-weight origin, authenticated source owner, physical Transformer forward or proof that gradients only touched authorized runtime state. Those require separate Worker/FinalUse, model admission, signed artifacts, and independent future-time NDU.

## Reproduction / cost accounting

```bash
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e1e2_q24_identity.py' -v
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e2_*.py' -v
```

The pinned hosted E1 three-model job executes the new identity tests and writes feature-bank proofs alongside the original per-case model-specific Q24 digest. The standalone E2 workflow tests the same pure-Python canonicalization. No new Encoder is loaded by these checks, and no encoder/vector caching or Zero-copy latency win is inferred from the hashes.

**Local evidence on the actual pushed code:** `e1e2_q24_identity.py` blob `f456dbe74d29cd3029cae80ee729bb1fb96a2e09`; `test_e1e2_q24_identity.py` blob `b1a43c5542f9e4847521a835016c89365feb7d19`; E2 study blob `8a89523edf4941944de721e0ee2392967b0a22e9` after pre-SGD validation relocation; E2 independent scorer blob `c2d62ed84a3e73da18ccab57d1ce825470c27264`; E2 mutation fault test blob `fe2af1b3072a35c683b317c9d6c67a246a69d0d0`. The exact latest E2 study and runner subsequently gain pre/post-frozen-bank stability checks and must be hashed again at final HEAD.

**150 local Python tests passed** across E1 source lock, three model fairness, E1+E2 numerical training and archive tampering, E3 public media and E4 reversal mechanisms. This includes *real PyTorch optimizer steps on synthetic vectors only*. It is not a production multi-Cell / 4,096 native Worker execution receipt, nor a new pretrained Granite/mmBERT/Gemma success. No Stem or Head is selected.

All new outputs preserve `production_promotion_permitted=false`, `authority=DENY_ALL`. Exact-head Actions and `blocking-ci` remain required; a queued job is not an execution result.

## Core-triad 768D research extension (2026-10-15)

The canonical Q24 bank now accepts an explicit **768D** width alongside 256D/384D so a proposed ModernBERT-base Stem can participate in the same scientific Feature Identity and frozen Head experiments. Domain separator, per-case signed Q24 coordinates, whole-bank canonical order, exact-case coverage and all no-authority flags remain unchanged. Width is included in every digest; 384D and 768D banks cannot alias. This is **not** an admission of real ModernBERT weights or target-Worker Q24 compatibility. The original E1 public triplet still has only its 256D/384D model registrations; a genuine matched three-way CPU/GPU study remains separately required.
