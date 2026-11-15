# Sparse/delayed ACT/CTRL no-feedback shadow contract — HOLD

Parent HEAD 63a2d1707098002481dd7110340e5495af7d8bab (PR #5976). Original source blob before patch 88cbd3c591313040668fb0f1d526cab17e0d4109. Distinct read-only reference contract: not original production owner or independent evaluator.

## Defect and precise repair

The shared shadow time_aligned_credit rejected every trace with valid training actions and zero delivered feedback. This excludes a legitimate sparse or delayed no-observation outcome instead of retaining matched=0 and an explicit missing-count. Original native Q24 comparator already accepted empty feedback; this patch aligns the reference's absence semantics.

Full-audit-only unobserved_action_count distinguishes no receipt from observed zero modulation. future_withheld remains an audit field; do not export either count or the full transcript digest as a frozen selection feature. Both paths always have DENY_ALL and never grant training or adoption authority.

Five directed tests cover all four credit arms, missing versus observed zero, future-only forensic records, invalid action fail-closed, and unknown feedback targets. This remains purely synthetic input: no real learning, independent evaluator, source-time attestation, production Q24 candidate, true NoUpdate, different next task C, or cold recovery.

## Actual red/green evidence

- SPARSE_FEEDBACK_RED.log: 5 tests, 6 failing/error subtests due to absence refusal. Measured 0.05 s wall, 0.04 s user CPU, 22,812 KiB peak RSS.
- SPARSE_FEEDBACK_GREEN.log: 49/49 complete relevant shadow tests passed. Measured 0.06 s wall, 0.05 s user CPU, 23,668 KiB peak RSS.
- Post-fix original code SHA256 e6559fe511cedf3d0bb8b1647ffb0038f3cce11146b4b9a7127f17da578ff376.
- New test SHA256 69b078e4d1588f27f1823b494b12a3e35905b886ec90fe43e82716cb71b74e21.
- HeptaRuntime ai395, CPython standard library; measures test-only CPU/wall/RSS, not all-in experiment costs.
- Final staged-worktree discovery passed 49/49, 0.09 s wall, 0.07 s user CPU, 23,988 KiB peak RSS.

## Continuing HOLD gates

Independent original Owner source/training/feedback/action time attestation; full Q24 production candidate and NoUpdate; cost-matched sparse/dense ACT/CTRL actual task outcomes; MEM typed replay, deletion, retention; A->independent future B->selection->different C->cold recovery; 2x2 Core x NDU with multi-seed matched full costs. No production adoption, model deployment, or Owner authority changes. Overall HOLD_NO_GO / DENY_ALL.
