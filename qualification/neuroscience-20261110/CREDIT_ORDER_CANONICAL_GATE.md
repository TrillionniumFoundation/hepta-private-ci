# HPCA four-mechanism credit: canonical accumulation versus transcript identity

**2026-11-12 UTC — reference-level RED/GREEN gate, HOLD_NO_GO / DENY_ALL.**

## Authority and exact source

- Base: [PR #6056](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6056) at commit `539fc25bf81a5f08c8b7688d55fcf979d86e85fb`, tree `a22ac8361045430df0cd34dc6992578aee401c15`.
- Target original Git blob: `qualification/neuroscience-20261110/study.py` = `120765264c7b4978a3a364cec00158c76e04c159`.
- This revision changes only credit accumulation order and adds a focused regression test. All other 88 parent reference tests were replayed without modification. It does not change native Owner code, model, weights, train/eval data, task sources, capabilities or deployed behavior.
- Host: authenticated HeptaRuntime `ai395`, Python 3.14.4; isolated workdir `/home/qq/hpca-credit-canonical-20261112-t6`.
- Synthetic deterministic three-action, three-feedback fixture with modulators `1`, `1e-16`, `-1`; cutoff 4, delay window 4, decay 1, group and L1 limits `1e-17`. Six permutations, no random seed or external evaluator. No neural model is loaded.

## Reproduced blocker

The unmodified implementation hashes feedback in receipt-digest order but accumulates floating-point credit in caller-supplied iteration order. Six permutations of the same receipts give **one transcript digest, one causal-training digest, but two numerical delta vectors** under cancellation. The frozen-prefix reference is affected as well. This addresses a previously unresolved [#5811 review](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5811) issue.

[Original RED log](CREDIT_ORDER_RED.log): 3 tests executed, 2 expected failures; the invalid-receipt negative passed. The RED process exited nonzero. This is a synthetic reproducibility counterexample, **not** a real model outcome.

## Change and execution

Reject malformed feedback receipt types before sorting, then iterate all feedback by canonical receipt digest for numerical credit. The existing canonical transcript and causal-training digest definitions remain unchanged.

- [GREEN focused original log](CREDIT_ORDER_FOCUSED_GREEN.log): **3/3 passed**, wall 0.12 s, user CPU 0.10 s, system CPU 0.01 s, peak RSS 22,368 KiB.
- [GREEN full original log](CREDIT_ORDER_FULL_GREEN.log): **91/91 passed** (the parent's 88 shadow tests plus 3 new tests), wall 0.29 s, user CPU 0.27 s, system CPU 0.01 s, peak RSS 22,312 KiB.
- Original process log SHA-256: RED `b80b9d88954b35d65cbe2997985980413da2505c4b844216e88f6e81a1d64c9d`, focused GREEN `27940e59a0a446ddd3d0143bf368c76ad6ec6c460603f21d8dbe866a5a5cdce4`, full GREEN `72492a7e46b212c350074e29a488760f7b57b97ec6b78beff57eceb6f77a5809`.
- Tested `study.py` SHA-256 `1af7bdb78654efcb6e301f7e89a24cf21e1ccf134526686dbf56cbff1b3289a1`; tested regression file SHA-256 `1014ff420ae2c662a283bf4e0b3c667320831e1e16e577210a587b2252ea2976`.
- Reproduction: from `qualification/neuroscience-20261110`, `python3 -m unittest -v test_credit_order_invariance` and `python3 -m unittest discover -p 'test_*.py' -v`. Cost numbers apply **only to brief Python shadow tests**; no training, inference, Colab/Kaggle, GPU, Owner, WAN or energy claim.

## Qualification boundary

Closes **only** the local reference numerical-order reproducibility defect. Hosted exact-head CI is a separate gate, not inferred from local results. Owner attestation, Q24 production candidate, A→independent B→NoUpdate/Adopt→different C→cold recovery, full ACT/CTRL costs, real MEM retention/revocation and Core×NDU 2×2 remain unverified. **HOLD_NO_GO / DENY_ALL**: Draft only, no merge, weight adoption, release or deployment.
