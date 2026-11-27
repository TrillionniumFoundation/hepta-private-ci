# HPCA frozen evaluator / resource opportunity roster — 2026-11-11

**HOLD_NO_GO / DENY_ALL.** This repairs only a shadow preflight contract for
future independently evaluated, full-cost HPCA tasks. It contains no
model training, native Owner attestation, independent future evaluation,
actual task outcomes, production release, or new research benefit.

## Failure and repair

Prior to this change, paired_evidence enforced evaluator identity and
offered resource ceilings *only within each four-arm episode block*. A
different training seed or later episode could use a new scoring/evaluation
digest, or a different resource ceiling, while producing a pooled seed-level
sign-flip p-value. Even after the matched family/episode roster repair in
#5954, this remained possible.

The new gate freezes per-family evaluator digest and opportunity tuple
(feedback_budget_bits, query_budget, training_budget, compute_budget_us)
across all episodes and independent training seeds.
Four arms must still match within each episode block; all seeds must have
the same family-by-episode-count roster. Different task families may have
distinct predeclared evaluators/opportunities. The training model
ability_digest may legitimately differ by seed.

This does not authenticate self-declared SHA-256 digests, nor establish
independent evaluator or original Owner custody. Actual elapsed costs can
differ even with equal opportunity ceilings and must still be measured.
No significance, family-wide benefit, or authority is granted.

## Reproduction and measured scope

- Parent commit dd90310817db4cc028f859174ed7e8413dc6f8c2
  (stacked on #5954; no native owner or parallel workspace changes).
- HeptaRuntime ai395, Python unittest.
- Red parent: 3 of 5 directed assertions FAIL as intended:
  evaluator changed between seeds or episodes; offered budget changed between
  seeds. Two valid protocol controls pass.
- Green candidate: 42/42 Python shadow contract tests pass.
- Measured resource costs in FROZEN_EVALUATOR_ROSTER_EXECUTION.log belong
  to small contract tests, NOT model training or actual inference.
- Test and source SHA-256 identities are recorded in that log.
- Existing B2 real CPU LoRA model negative result remains; this change
  does not override it.

## Still open

Native Owner source/training/feedback/action-time attestation; original
Agentd A→training→independent future B→NoUpdate/Adopt→different task C→
Root/daemon cold recovery; seven-lineage cost-matched studies; sparse/dense
delayed ACT/CTRL; MEM exact RAG/fact/episode/skill/recovery deletion and
old-task/OOD retention; Core×NDU 2x2 attribution, repeated seeds and
multiple-comparison control.

**No deployment, no automatic adoption, no enlarged Owner rights.**
