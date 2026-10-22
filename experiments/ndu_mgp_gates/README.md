# NDU-MGP: P0–P4 qualification (research-only)

This branch starts at the PR #3055 frozen research candidate. It adds evidence gates without modifying any frozen experiment, heldout labels, model weights or execution authority. All research phases currently remain BLOCKED. The independent mathematical/oracle preflight in #3055 does not certify P0 end-to-end. The corrected new-heldout v1.1 result of #3039 failed its preregistered primary efficacy claim and is retained rather than pooled with the initially positive v1 result.

Run `python3 experiments/ndu_mgp_gates/verify.py experiments/ndu_mgp_gates/qualification.json` (expected HOLD_NO_GO, exit 1). This validator is **only a structural check**, not a cryptographic signature verifier, independent observer or proof of experiment outcomes. A fake HTTPS URL and SHA could fool it; reviewers must open and authenticate exact source, external evaluator, heldout split and evidence before any gate becomes PASS.

## Dependency order

- P0: independently verify continuous latent shared Encoder → immutable conditioning → base flow/Cell deltas → decoded outputs; compare Riccati, BVP, condensed QP, finite-difference gradients and nonlinear-approximation error; require exact-head CI and actual runtime receipts.
- P1: same inputs/model/actuators and measured compute for fixed portfolio, MoE gate, risk-neutral MPC, fixed-risk MPC, free neural controller and NDU. Predeclare CVaR, truth, contradiction, ambiguity, diversity, total physical cost and practical effect; use untouched future-window evaluation and strong baseline.
- P2: freeze masked diffusion backbone and tokenizer; compare shared-vocab logit portfolio, atomic unmask schedules and stopping against equal-budget masked diffusion baselines. No mixing incompatible protocols or live test-informed tuning.
- P3: natural text-image, text-speech and image-speech outputs, independent factual readback, synchronization, streaming/irreversibility safety and device-specific end-to-end latency; video after verified prerequisites.
- P4: preregister factorial training-only, inference-only, combined, neither, and equal-capacity non-NDU controller; hold external utility and evaluator fixed; ensure no protected subgroup regression, cold-start/shift robustness, prospective replication and independent authority review.

All five phases are research-only; no native authority, Cell split, optimizer-artifact promotion, model deployment or final-use grants. Review [#3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055), [#3039](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3039) and [NDU FBSDE spec](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/main/docs/learning/NDU_FBSDE_SPEC.md).
