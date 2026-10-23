# CORE c1 t2: completed, confirmatory claim failed

This was executed in the saved hepta-private-ci Codex Cloud environment, not a
scratch environment or Actions. TRAIN/validation exited **0** and passed the
frozen readiness screen. The sole formal evaluation then exited **1**:
`benefit_verified=false`. Keep this scientific failure and both opening markers.
Do not rerun, replace, recycle, or tune against this held-out set.

## Frozen identity and actual execution

- Source: `cff9562102a21eb2a852daa61810e2e0b576ed9d`.
- Build execution/freeze commit: `8ca460b29d4bdb7a117a72074fa18ee8e06c1064`.
- Preopening artifact/formal execution commit: `06837d982fa314a80e6f8fb06f8e213af68d4cc5`.
- Protocol: `core_confirmation/PROTOCOL.md`, SHA-256
  `1dc19b8b52baef0963e26d7af8886a713a007db5876bfffb5774b1550a08313c`.
- Plan SHA-256: `94d84d8eb1af73c4c766604b3ddbcac0be2d9a2b1638b2afa10acf8216c2762b`.
- Freeze: `core_confirmation/frozen-core-c1-v2.json`, SHA-256
  `8f969a4953465228af05c507dfa7a43c195f74041ac25411b0a7d3e4b6ad21e8`.
- Selected Cloud environment:
  `ccarenv_b64_Y2NhcmVudl8wOGNhYzlkMjdjYjg4MTkxOWJkMDY0MGIyMDBhYTA5OA`.
- Working directory: `/workspace/hepta-private-ci/qualification/joint-generation`.
- Python 3.12.14; NumPy 2.3.5; Pillow 12.3.0; GCC 14.2; single-threaded
  OpenBLAS/OMP/MKL. Actual backend and compiler receipts are in selection/telemetry.

Both commands used `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
PYTHONDONTWRITEBYTECODE=1`:

```bash
python -m independent.run --experiment core-c1 train --freeze core_confirmation/frozen-core-c1-v2.json --out runs/codex-cloud-core-c1-t2
python -m independent.run --experiment core-c1 evaluate --run runs/codex-cloud-core-c1-t2
```

TRAIN ran 2026-10-23 14:32:38.469226–14:33:06.020393 UTC. Its full child CPU was
27.539362 seconds across the four builds; each arm's independently capped cost
includes the entire shared preparation. This aggregate is not one arm's cost.
Formal evaluation ran 14:40:43.799820–14:40:49.589451 UTC, full child CPU
5.788599 seconds, including preflight, service, observer, bootstrap and result
persistence. These formal evaluation/R&D costs do not replace measured service
CPU or give a credit against build budgets. Outer launch costs remain separately
recorded in `execution.json` and `evaluation-execution.json`.

## Trainability, useful baselines and complete costs

All 12 selected models changed all 7,288 content entries in the shared encoder
and both content heads from their corresponding newly trained base. Their learned
decoder and decoder bias remained exactly fixed. There were 36 real LR candidates,
with no discarded objective gradient, unused critic, or padded route. Selection
and calibration preceded opening. `preopening-audit.json` records those checks.

| Arm | Complete build CPU, seconds | Declared operator units | Selected updates, seeds 11/23/47 |
| --- | ---: | ---: | --- |
| Supervised S, CE 1.0 | 9.446719911 | 10,607,956,859 | 497 / 481 / 490 |
| Anchor H, CE 0.2 | 9.616731124 | 10,421,593,721 | 533 / 459 / 388 |
| Additive A, CE 0.2 | 9.595203997 | 9,293,559,091 | 462 / 432 / 249 |
| NDU N, CE 0.2, rho 1.5 | 9.502996020 | 9,871,183,893 | 438 / 400 / 343 |

Each arm includes all 3.785431454 seconds of shared preparation, compilation,
base/decoder training, calibration and common validation, plus its own candidate
training/search, selected residual training, validation and export. Every arm
held the unchanged 10-second/12B caps; zero service budget violations occurred.
Calibration used 72 distinct TRAIN physical sources, exactly six of every source
and target class, in six balanced rounds. Every timing sample is retained.

## Sole formal result

The unopened test contained 72 new physical sources and 1,152 rows, using all
three model seeds. They remain the same twelve-class synthetic task, not new
semantic concepts. Its saved input artifact is `test-inputs.npz`, SHA-256
`da5d2fb3accc6b3564b0408f4fb5fe7d80f865dfcb8363436901197dc347d137`.
All twelve arm/seed systems' per-row metrics, batch cost cohorts, corruption
controls and intervals are retained in `test-result.json`.

The protocol requires **all six** lower bounds to be positive. None was positive:

| Fixed contrast | Endpoint | Mean | 95% interval |
| --- | --- | ---: | --- |
| A minus H | Raw task utility | +0.011477969 | [-0.002448483, +0.022745976] |
| A minus H | Joint success | +0.011794093 | [-0.003381344, +0.023805726] |
| A minus H | Complete CPU-net | +0.011488803 | [-0.007769029, +0.024386872] |
| N minus A | Raw task utility | +0.005739066 | [-0.006458845, +0.019752755] |
| N minus A | Joint success | +0.005889641 | [-0.007273004, +0.021032829] |
| N minus A | Complete CPU-net | +0.005840754 | [-0.007389146, +0.023056095] |

These are the predeclared 2,000-replicate crossed seed/cluster paired percentile
intervals, seed 77431. Raw/joint metrics use 72 physical-source groups; CPU-net
uses 18 fixed service-batch cohorts. CPU inference is conditional on this fixed
execution wave and batching. No alternate resampling, omitted seed, trimmed CPU
sample or changed gate was used.

All seeds were reported; decoder corruption reduced score for all 12 bundles;
maximum greedy drop was 0.011284722, below 0.02; budget violations were zero.
Those engineering/negative-control gates do not establish the six failed
incremental-benefit claims. Positive report-only N-minus-S intervals also cannot
replace A-minus-H and N-minus-A or turn this failed conjunction into a pass.

## Scope and remaining work

The trainable two-modality implementation and reserved canonical modality
interfaces are real. The independent same-complete-budget content-control and
NDU benefit claim is **not confirmed**. This result does not prove no benefit;
the frozen experiment did not distinguish both contributions from zero with its
required uncertainty bounds. No runtime or score-accounting defect has been
identified that invalidates the result or permits another opening.

The original core t1 calibration-construction failure, all r2 failures, and the
narrow r1 result remain unchanged. R2's formal test remains unopened and its
stronger dynamic continuation net-benefit gate remains failed. Synchronous AV,
long interaction, natural images, device and production qualification are unrun.
No merge, deployment or permissions change occurred.

Further model or compute changes must be justified only with TRAIN/validation
evidence. A later confirmation needs its own prospective scientific protocol and
independent evidence; another test seed or larger sample cannot be substituted
into this result. The existing statistical gates and failure stay visible.
