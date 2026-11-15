# Hosted physical derivative readback for #6206

These are existing GitHub Actions originals from source `d4e7ecd239988790936f21407be1ba05c318c6d8` (tree `95151445f8a2674d7b8a5bdf8e90969acd8792ac`). This evidence commit adds zero model executions, optimizer calls or independent complete training replays.

| Geometry | Existing run / job | Actual Adam calls | Probe wall seconds | Original ZIP bytes / SHA-256 |
| --- | --- | ---: | ---: | --- |
| Uniform | [43176653395 / 131042400189](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43176653395/job/131042400189) | 4 | 16.922846431 | 39840 / `9384d7e9fd441d4cce5a32cadcd5ed8b76316a5bbeb4e407dc1277180d016170` |
| Graded | [43176653540 / 131042400886](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43176653540/job/131042400886) | 4 | 16.999670788 | 39874 / `b3d03d695008f153495d502430efccf3743c9fbd71a9ed36a366d31f3c0a7531` |

Both jobs succeeded at the exact source head, under Python 3.12.16, Torch 2.8.0+cpu, NumPy 2.3.5 and SciPy 1.17.0. The graded log records 8 NumPy tests passing. Each existing probe records successful native gradcheck, parameter-version and unsafe-data mutation guards, initial-state refusal, source/runtime mismatch controls, and exact full-state comparison between continuous two steps and one plus fresh-process one step.

The archiver independently downloaded both complete ZIPs, checked their advertised size and SHA-256, read all 19 members per archive with CRC and member hashes, matched each checkpoint hash to its RESULT receipt, compared retained continuous/resume records, and re-fetched all 9 source commitments at the exact source SHA. Each `RESULT.json` here is an unchanged member of its adjacent original ZIP. Complete decoded GitHub job logs and API metadata are retained. Temporary signed download URLs are omitted.

This archival check did not deserialize Torch tensors or recompute derivatives. Full-state equality and gradient-control flags remain the existing producer results; they are not a new independent numerical audit. Probe wall and CPU figures exclude dependency installation and complete hosted job cost. These fixed-prior CPU FP64 physical-VJP probes do not establish whole-network gradients, task efficacy, full C2 training replay, energy savings or production admission. HOLD_NO_GO.

All added paths are under `qualification/hcsn_ci_readbacks/6206`, outside the source/workflow path filters of the two physical-model workflows. No source head, workflow, source file or existing original was changed; no workflow rerun was requested. No formatter was applied to retained original bytes.
