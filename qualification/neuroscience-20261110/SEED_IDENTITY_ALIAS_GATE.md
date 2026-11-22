# Core×NDU declared seed-identity anti-alias guard — 2026-11-11

**RESEARCH_ONLY · HOLD_NO_GO · DENY_ALL.** This is an input consistency control, not attested seed custody, independent future evaluation, a model training result or a qualified production candidate.

## Source, test identity and conflicting parallel work

- Existing exact parent: [#5970](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5970) HEAD `d043d134f099c7c24a8dafdcda77593b97378179`, tree `8e0a4057732c06aa1c05c2eae598550757953d55`. Scoped to two files within `qualification/neuroscience-20261110`, preserving original parent, current main and other ACT/MEM/owner PRs.
- Original unmodified parent factorial.py Git blob `96f6a69c9bb11232591d061f41cea31d2a1bb75c`; new locally tested content SHA-256 `0682196fe8c8a1edb8d6f75aa56da4c7a3479fc8859ca44cbdc96d4c50a1ca38`, Git blob `c9b4b914bdbbe66c5b410b114c5b09724035222b`.
- New test source SHA-256 `301aa51eff654dbe24791ae5a2f662fb6eb9272b577b765aadf4213cfa6b02d9`, Git blob `92a24ea14819dea0c211560c7e55a1481892a8fb`.
- Original unchanged `study.py` and `test_factorial.py` loaded from #5970 via the GitHub connector, not reauthored or merged from another tree.
- Operator: configured HeptaRuntime `ai395`, Linux, Python 3 stdlib, isolated `/home/qq/work/neuro4-seed-isolation-20261111-r6/qualification/neuroscience-20261110/`. Attempted native Git fetch for exact #5970 branch failed with missing blob `ae0bd24ca843764361d8fa2e52be1475dadf77c9`; recovered each of the *four Python source files* directly from the exact GitHub parent via read-only connector. This is an explicit native Git transport limitation, not evidence of source drift.

## Reproduced failure

Before the fix, the Core×NDU preflight would count different integer training-seed labels as independent `seed_clusters` while accepting **identical declared training seed digests**, permit changing the training-seed identity within a cluster across task cells/episodes, and allow two labels to reuse the same declared evaluation-seed digest or to alias another cluster's training seed. This silently undermines any attempt to interpret seed-level sign-flip p-values as independent cluster evidence.

Original RED test suite: `python3 -m unittest -v test_seed_identity`; **five of six tests failed as expected**, one legitimate episode-varying future-eval seed control passed. The full untouched output including traceback and resource summary is in `SEED_IDENTITY_RED.log`. Wall 0.04s; user CPU 0.04s; system CPU 0.00s; peak RSS 23,692 KiB. Launcher Job `1a1caa517c3-2564-795`. Tests use synthetic declared digests for seeds 0 and 1, NOT actual models, frozen evaluator receipts or genuine task consequences.

## Minimal repair and verification

- A training seed label cannot change its training seed digest across episodes or family/density cells.
- Distinct seed labels cannot declare identical training seed digests, nor share any evaluation seed digest.
- Across all rows, no evaluation seed digest may alias any declared training seed digest, even if it belongs to another cluster.
- Different evaluation-seed digests **within the same training seed cluster** are still accepted, allowing separately frozen future task episodes.
- Within-arm, within-block, frozen evaluator/opportunity checks and declared `HOLD_NO_GO` posture remain untouched. A new `coverage.declared_seed_identity_alias_guard='SELF_DECLARED_ONLY'` field prevents a false claim of authenticated seed custody.

Original GREEN: `python3 -m py_compile factorial.py test_seed_identity.py`, `python3 -m unittest discover -v -s . -p 'test_*.py'`; **40/40 tests passed**, including all inherited shadow study and Core×NDU factorial tests. Full raw log `SEED_IDENTITY_GREEN.log`. Wall 0.19s; user CPU 0.18s; system CPU 0.00s; peak RSS 23,264 KiB. These are ONLY test process costs, not model lifecycle costs.

## Remaining qualification (ALL HOLD)

No actual training/model/data/config hashes, owner attested source/feedback/action timestamps, native Q24 adopted candidate, measured ACT/CTRL sparse/dense results, MEM no-resurrection real replay, independent prospective B/evaluator, legitimate 2×2 task advantage, old task/OOD retention, genuine NoUpdate/Adopt, distinct C or Agentd cold restart are established by this synthetic guard. Identical physical RNG states can still be assigned distinct arbitrary SHA-256 strings; this code cannot authenticate their provenance or statistical exchangeability. All production/science gates remain **HOLD_NO_GO / DENY_ALL**. Do not merge, deploy or grant model update authority on these checks alone.
