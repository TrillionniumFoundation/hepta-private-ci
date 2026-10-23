# NDU-MGP P1 shadow: protected-cohort and hard physical budget gate

Research-only, fail-closed source change. Adds no real decoder, independent source authentication, NDU policy efficacy, or FinalUse authority.

## Frozen data contract

`protocol.protected_world_ids` is required: a map from each registered training seed (string) to a nonempty set of at least two of that seed's preregistered heldout IDs (represented as a duplicate-free list). The manifest must exactly cover all seeds and may not refer to another seed's heldout IDs. Every `world.protected_task` bool must match that frozen per-seed manifest. This catches accidental/reported-after-evaluation relabeling. Both the manifest and raw data are still caller-provided and require an independent evaluator / immutable external source, not just their own hash.

`protocol.episode_cost_limit` is required, positive, finite, and shared by all seven arms in the same physical unit as each `measured_cost` receipt. The ceiling applies to **every observed episode**, never merely to the ratio of average costs. An episode whose total physical cost exceeds the cap must have **every** draw marked `failed` with full preregistered failure loss/quality/ambiguity/inconsistency, preserving that episode in the analysis denominator. The paired physical-cost gate fails if NDU or its comparator exceeded the absolute cap anywhere, even when the ratio of mean costs is below the 1.05 limit. The report also publishes per-arm overbudget episode counts.

No source change is made to the frozen PR #3055 continuous latent experiment or PR #3039 / #3213's previously observed negative evaluation. This does not qualify strong NDU superiority, future windows, real generation or actual end-to-end physical cost; the supplied receipt fields still require independent measurement/authentication. Keep `DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.

## Local CPU verification

- Original 41 reconstructed unit tests + 7 new tests = 48, all actually executed on Python 3.13/NumPy 2.3.5 at the tested blobs.
- Tested blob `paired_superiority.py`: `959e8d3bbb8ab28ebdd5bf18c04dfc039b78e1f9`
- Tested blob `test_paired_superiority.py`: `cdbbd7f219145641bdb1369efef290c2a27e13ad`
- The comparative 2,000-replicate synthetic fixtures remain **synthetic** and can only exercise the evaluator logic, never prove real NDU superiority.
