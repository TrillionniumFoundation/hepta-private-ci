# Core×NDU frozen episode-roster gate (2026-11-11)

**RESEARCH_ONLY · HOLD_NO_GO · DENY_ALL.** This is a synthetic, self-declared input-consistency fix, not evidence of neurological learning benefits, owner attestation, independent evaluation, or production eligibility.

## Parent and provenance

- Exact independently fetched GitHub parent: [PR #5973](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5973) at commit `789e6d0d87234e584738db346d74548c7e83fc48`, tree `9b55935accbeb7d547786a608d225b041f415b1f`.
- Changed only the Core×NDU preflight `factorial.py` plus a focused test and two raw logs under `qualification/neuroscience-20261110/`. Existing owner, model, MEM, ACT and concurrent worktrees were not changed.
- Unmodified parent `factorial.py` Git blob: `c9b4b914bdbbe66c5b410b114c5b09724035222b`.
- Actual independently executed patched `factorial.py` Git blob: `fe072010761a4bd1d0f500e6ca21c0ebe54a5d6e`.
- Actual independently executed new `test_episode_roster.py` Git blob: `c189f954090dde817d4dccd45d30a153ce70ba4d`.
- Original unmodified supporting test source: `test_factorial.py` blob `b43d8f270b46578e2f0d5427f3425ab3363c5170`, `test_seed_identity.py` blob `92a24ea14819dea0c211560c7e55a1481892a8fb`. The original `study.py` was also copied from that exact parent.

## Original failure and bounded fix

The preceding #5970 contract required equal *counts* for each cell and seed, but did not compare self-declared episode identities. For two seeds, the second seed could replace `ep1` with `replaced_ep1`, retain the same count and four valid A/B/C/D arms, and still receive exploratory paired statistics.

The new gate builds a set of episode labels per (seed, family, feedback density), then requires those sets to match across training-seed clusters *within the same registered cell*. Different task families or densities may retain different, preregistered episode sets. Independent per-seed future-B workload digests are not falsely equated; all identities remain self-declared.

## Raw execution and resources

- Configured HeptaRuntime `ai395`; isolated original workspace `/tmp/hpca-neuro4-episode-roster-20261111-t6` (no shared tree modified); local Python 3 standard-library unit tests.
- Red test with exact original parent preflight: 3 executed, 2 passed, 1 **failed** as expected (`ContractError not raised`). Original durable execution ID `1a1cadfd25d-2564-8c0`; saved `EPISODE_ROSTER_RED.log`. Red CPU user 0.10 s, sys 0.01 s, wall 0.12 s, max RSS 22,884 KiB.
- Patched full relevant test discovery: **24/24 passed**. Original durable execution ID `1a1cadfd25d-2564-8c0`; saved `EPISODE_ROSTER_GREEN.log`. Green CPU user 0.44 s, sys 0.01 s, wall 0.46 s, max RSS 22,928 KiB.
- The three added tests cover substitution rejection, valid matching cohorts, and legitimate different rosters for different registered cells.
- Actual model/data/config/seed: **no model or training data were loaded**. Tests use deterministic synthetic `panel` from the recorded unit-test source, with labels for seeds 0 and 1, test family ACT, sparse/dense feedback cells and fixed A/B/C/D arms. No real task evaluation, network effect, signed receipt or performance/benefit observation was made.
- Local source/test SHA-256: patched `factorial.py` `00360607eaf0dfba5a7538200c16796662f244c04e8abd98fe273793eac9df91`; `test_episode_roster.py` `7973592a7d636169932f3314b69e29b00de73046dfd909fabcf645ee7184d632`.
- Original raw log SHA-256: red `ea252d6575e2c65f01f71ecd67cf1a4d2761efb8793880522c4a529718861fd`; green `e87f2487046c9799d7a5c597ad5e80f25699b23039cc50d4fa93c222a80c908e`.

## Non-closure

Self-declared `episode_id` equality does **not** establish equal underlying tasks, frozen holdout custody or independent future evaluator. All owner-attested source/training/feedback timing, Q24 production candidate, actual seven-lineage cost and ACT/CTRL effect experiments, MEM deletion/recovery, real A→train→independent B→NoUpdate/Adopt→different C→cold recovery, and matched Core×NDU 2×2 net benefit remain **HOLD_NO_GO / DENY_ALL**. Hosted CI must be evaluated on the newly published exact HEAD before marking even this contract fix as hosted-verified. No merge, weight adoption or deployment is authorized.
