# Hosted bounded initial-amplitude VJP readback for #6241

This archive retains the existing successful GitHub Actions [run 43193514377 / job 131098507245](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43193514377/job/131098507245) at exact source `8945243ae3f0832c01e317498be71483413b8b7b`. The archiver performed zero candidate, model, Torch, DDE or optimizer executions.

| Existing result | Recorded value |
| --- | ---: |
| API / basis DDE forwards | 39 / 39 |
| Independent uniform native oracle forwards reported | 2 |
| Optimizer updates | 0 |
| Probe wall / CPU seconds | 12.909670168 / 12.851068008 |
| Peak process RSS | 422920 KiB |
| Original artifact ZIP | 11609 B; SHA-256 `e95849561120270999ec2f3add8ebb863b1ed72d159e851c0569190f716587c6` |
| Raw initial-amplitude VJP coordinates retained | 69 |

Runtime is CPU / one thread, Python 3.12.16, Torch 2.8.0+cpu (build `a1cb3cc05d46d198467bebbb6e8fba50a325d4e7`), NumPy 2.3.5 and SciPy 1.17.0. These probe costs exclude full hosted job setup and dependency installation.

The complete original ZIP has four members: `initial-amplitudes/RESULT.json`, `CALLS.json`, `ARRAYS.npz`, and `initial-source.json`. Their raw bytes are retained in the ZIP and convenient adjacent copies. This readback checks complete ZIP size/SHA-256, every member CRC/hash, output NPZ bytes and its 15 numeric NPY member headers/hashes, all 39 call-journal records and their basis/optimizer totals, exact checkout and all 13 source-before/source-after commitments against fresh GitHub source bytes. It also rehashes the retained development archive and its expected-array receipt at the same source head. Complete decoded job logs and API metadata are retained; temporary signed download URLs are omitted.

The existing result records both positive-amplitude raw gradchecks, all-four-input mutation controls, the old physical-only prior refusal, uniform native-oracle comparison, and the explicit normalized-client softmax/content-binding check. This archival read does not recompute VJPs or import candidate/Torch code. The normalized-client flags and scalar discrepancy are retained; separate raw normalized-gradient vectors are absent. `ARRAY-INDEX.json` makes this distinction visible.

Scope remains fixed physics/support on two disclosed small fixtures. No n512, full-network, migration/filter/support/physical gradient, automatic normalization of independent amplitude blocks, complete training/C2, energy or production admission follows. HOLD_NO_GO.

All changes are under `qualification/hcsn_ci_readbacks/6241`, outside this workflow's model-source path filter. No source head/workflow/original was changed, no rerun was requested, and no formatter was applied to retained original bytes.
