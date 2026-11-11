# Core × NDU factorial preflight: frozen cell and equal seed opportunity (2026-11-11)

**RESEARCH_ONLY · HOLD_NO_GO · DENY_ALL.** This is a *shadow evidence-integrity guard*, not an owner-attested run, a scientific improvement, independent future B, real model training, or an adoption/release authorization.

## Original parent and independently reproduced defect

- Parent [PR #5967](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5967): HEAD `b8ea1b0158b0d46b6be342fba4c5521c9f8bd3f7`; changed source blobs `factorial.py=a446f1b06e66c9ab7135654cc2e3f1b54337e840`, `test_factorial.py=07945d9aac7dc479d288ec503223fc1b39a659ef`. Unchanged `study.py=43d4e644fa38be1820c0b722e6e94c77740c19e7`.
- The existing four-arm per-episode check correctly matches A/B/C/D *within* each episode; however, evaluator and opportunity can be changed across episodes or training seeds in the same registered task-family/feedback-density cell. Two different seed clusters can also contain unequal numbers of episodes yet yield numeric p-values and `complete_for_declared_matrix=True`.
- An isolated regression run on authorized HeptaRuntime `ai395`, job `1a1ca937fd4-2564-6ee`, ran **15 directed tests, 3 expected failures**: changed evaluator across seeds, changed query ceiling across episodes, and unequal per-seed episode opportunity. The fourth new control (different evaluator/budget *between* separately registered dense/sparse cells) passed on the unpatched source. Full original output: `FACTORIAL_CELL_ROSTER_RED.log` (including time/RSS).

## Minimal guard

- For each registered `(family, feedback_density)` cell, freeze self-declared base model, capacity, evaluator, feedback bits, query/training budget, and compute ceiling across all seeds and episodes. Allow different registered cells to use different frozen contracts, and allow per-seed task, training seed and evaluation seed to differ.
- Require *identical episode counts* within a registered cell across training seeds. A different task family may have a different count. This closes obvious selective-denominator pooling; it does **not** verify prospective sampling or identical selection processes.
- Add report flags `coverage.equal_episode_opportunities_per_seed=True` and `coverage.frozen_cell_contract="SELF_DECLARED_ONLY"` so an accepted input is never mistaken for signed provenance.

## Green original execution

- Job `1a1ca95203e-2564-6fd` on `ai395`, isolated source copied from exact parent and then patched. Python stdlib `py_compile` succeeded; **34/34 tests passed** (15 factorial + 19 inherited study tests), no exceptions.
- Full output: `FACTORIAL_CELL_ROSTER_GREEN.log`. Directed RED cost: wall 0.18 s, user CPU 0.17 s, RSS 23,804 KiB. GREEN cost: wall 0.17 s, user CPU 0.17 s, RSS 23,444 KiB. Costs are test-invocation only, not actual model training, evaluation, or lifecycle cost.
- Full SHA-256 input/source and test hashes before and after appear in `FACTORIAL_CELL_ROSTER_SOURCE_SHA256.txt`. The final tree is separately checked against GitHub blobs after publication.

## Residual qualification (OPEN, unchanged)

The input rows, SHA-256 strings, actual CPU, wall/RSS, model capacity, evaluator independence flags, and utility/cost values are supplied by the caller. Cross-seed and per-cell parity does not authenticate an owner, prove externally observed outcomes, establish seed exchangeability, lock a truly independent future B, or prove cost-matched neurological mechanism advantage. Independent owner A→train→B→NoUpdate/Adopt→distinct C→cold recovery, sparse/dense ACT/CTRL, MEM deletion/retention, and the complete Core × NDU 2×2 real tasks remain HOLD. Do not merge or deploy on this synthetic contract evidence.
