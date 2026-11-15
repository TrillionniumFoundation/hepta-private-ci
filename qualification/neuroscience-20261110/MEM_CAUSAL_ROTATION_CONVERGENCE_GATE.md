# Frozen MEM causal prefix x seed-rotated stratified replay

**HOLD_NO_GO / DENY_ALL.** No production Owner authority, source-attested
time, learned model benefit, independent evaluator, adoption or deployment.

## Exact inputs and integration lineage

- First parent: frozen-prefix MEM read-only PR #6024,
  9d90eee116002530a402ec2b8d47a1641d9f7653,
  tree 70f6d8cf67ee5c23e498a330ce2d6c3ef4ec2d2b.
- Second parent: seed-rotated MEM kind scheduler PR #5966,
  35ebd71e2572de08decef28af5d224a5a9437b24.
- A local no-ff merge of original commits was conflict-free. This retains
  original per-parent evidence rather than rewriting either PR.
- New cross-mechanism test: test_frozen_seeded_mem_convergence.py, including
  original raw RED/GREEN/full-suite logs in the git tree.
- HeptaRuntime ai395 configured operator host, system python3, deterministic
  synthetic four-kind records, 128 *declared* seed strings. No ML training,
  inference, model weight, GPU, Colab, Kaggle, native Owner action, or external
  evaluation was used.

## Joint acceptance cases

1. All four live memory kinds appear in budget-one stratified selection across
   fixed seeds; the old fact-first implementation excluded three kinds.
2. Invalid future post-cutoff duplicate/receipt data cannot alter frozen
   stratified selection; the forensic whole-input API still rejects it.
3. A visible logical-object tombstone blocks both the old fact and attempted
   later revival, while a prior frozen view sees the old fact. Other kinds
   remain selectable after deletion.
4. Exact-key RAG output and full four-item stratified coverage are preserved.

RED test against #6024's exact original study.py: 4 cases, 2 predicted
failures. GREEN integrated candidate: 4/4 passed. Complete reference suite:
80/80 passed. Git diff --check passed.

## Measured local process costs (not full application cost)

| Process | Wall s | User CPU s | Sys CPU s | Peak RSS KiB | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| RED | 0.04 | 0.03 | 0.00 | 23456 | 1 |
| GREEN | 0.04 | 0.03 | 0.00 | 22804 | 0 |
| Full suite | 0.06 | 0.05 | 0.00 | 24328 | 0 |

Postmerge study.py SHA256:
56eef7dffe9994f9d2775f5b771a99c3e7aa1b3b6824d380626a49c36b1f881a
New cross-test SHA256:
489aaf7b8ed6f8177e0de17e266301d46b0d186e7b8e80a772a424211f4814e1

## Limits and remaining acceptance gates

This merges two existing shadow contracts and tests their interaction; it is
not real learned improvement, native MEM deletion, independent validation, or
a new production candidate. Seed and time claims are unauthenticated. The
rotated stratification is a changed baseline policy; do not pool historical
fact-first results with this policy version.

HOLD: Q24 owner source/action/feedback identity and timing; independent B,
real NoUpdate/Adopt, different C and cold daemon/Root recovery; fact, episode,
skill and recovery replay vs exact-RAG/uniform/typed full-cost strong controls;
seven-lineage real costs; ACT/CTRL sparse/dense terminal effects; multiple-seed
Core x NDU 2x2 attribution. No authority was added.
