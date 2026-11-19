# Hosted small-mesh physical Torch readback for #6234

These are existing GitHub Actions originals from source `a385c0fe6fafc513da8539799338182176a1a9f8`. This evidence commit adds zero model executions, optimizer calls or independent complete training replays.

| Geometry | Existing run / job | Actual Adam calls | Probe wall seconds | Original ZIP bytes / SHA-256 |
| --- | --- | ---: | ---: | --- |
| Uniform | [43183355160 / 131064470735](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43183355160/job/131064470735) | 4 | 13.209626450 | 39833 / `52cc14a45dc19c9525f46004d98260a16f98b13d17b148a5c5a5a0e2354a2564` |
| Graded | [43183355248 / 131064470498](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43183355248/job/131064470498) | 4 | 11.363237610 | 39865 / `e3ba8b9b0f4313468d22730ae205e43f5349a1a4c1c6f2c4222e67d2e18aebdb` |

Both jobs succeeded at the exact source head, under Python 3.12.16, Torch 2.8.0+cpu, NumPy 2.3.5 and SciPy 1.17.0. The graded log records 8 NumPy tests passing. Each existing probe records successful gradcheck, parameter-version and unsafe-data mutation guards, initial-state refusal, source/runtime mismatch controls, and exact full-state comparison between continuous two steps and one plus fresh-process one step.

The archiver independently downloaded both complete ZIPs, checked their advertised size and SHA-256, read all 19 members per archive with CRC and member hashes, matched each checkpoint hash to its RESULT receipt, compared retained continuous/resume records, and re-fetched all 9 source commitments at the exact source SHA. Each `RESULT.json` here is an unchanged member of its adjacent original ZIP. Complete decoded GitHub job logs and API metadata are retained. Temporary signed download URLs are omitted.

This archival check did not deserialize Torch tensors or recompute derivatives. Full-state equality and gradient-control flags remain the existing producer results; they are not a new independent numerical audit. Probe wall and CPU figures exclude dependency installation and complete hosted job cost. These inherited small-mesh fixed-prior CPU FP64 physical-VJP probes do not qualify n128/n512 Torch, whole-network/prior gradients, task efficacy, full C2 training replay, energy savings or production admission. HOLD_NO_GO.

All added paths are under `qualification/hcsn_ci_readbacks/6234`, outside the unchanged source/workflow path filters of the two physical-model workflows. No source head, workflow, source file or existing original was changed; no workflow rerun was requested. No formatter was applied to retained original bytes.
