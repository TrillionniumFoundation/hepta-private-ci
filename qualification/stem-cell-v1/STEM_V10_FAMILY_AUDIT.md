# V10: independent family-level negative audit over existing original V9 evidence

## Scope and source of truth

This additive research-only checker uses existing `STEM_V9_POSTSEAL_WEAK_SCORES_20261015.json` from the latest V9 original MiniLM LoCoMo negative experiment. It does not perform a new Encoder forward, training update, Reader answer or semantic adjudication. The V9 aggregate is an unchanged input, not new material; no user dialogue, model weight or private answer is added.

The retrospective test has 829 questions but only **four** independent conversation roots: conv-47 (190), conv-48 (239), conv-49 (196), conv-50 (204). Seven total labels are unannotated. Do **not** treat 829 correlated questions as 829 independent samples, or three training seeds as distinct data populations. Aggregated counts cannot reconstruct individual paired successes or compute a valid paired McNemar statistic.

Under the actual V9 protocol, BM25 weak publisher-support Hit@3 = 372/829, frozen dense = 223/829. Learned Head counts across the three seeds and continuations range from 2 to 78 / 829. All 12 Head conditions are worse than BM25 in each of the four source roots. This is a descriptive retrieval proxy and not Reader semantic accuracy.

## The research guard

`stem_v10_family_audit.py` rejects any changed arm census, altered family sizes, missing/extra root, negative or bool counts, inconsistent missing annotations, altered original totals, fake human scores, fake future windows and promotion. It records per-family rate contrasts and count differences. It refuses any implication of valid paired-task significance or production selection. `test_stem_v10_family_audit.py` has 16 stdlib-only adversarial tests in normal Python and `python -O`.

The original V6 cross-fact Reader seed41 retention failure remains unresolved by the different V9 MiniLM Head task. V9 train-only replay preservation does not establish cross-family generalization. V10 is **DRAFT / SHADOW_ONLY / DENY_ALL**. No main merge, FinalUse, automated Cell fission/fusion or model selection.


The actual V9 original JSON raw SHA is pinned to `aee4f44188e005b689fec7d472900ea9ad76e11a08ece772a89401fecfdfd544`, and the original prediction SHA is also checked. A modified source rehashed after the fact is refused. No Reader answer calls, future windows, independent semantic judgments or matched full lifecycle compute can be inferred from this audit.
