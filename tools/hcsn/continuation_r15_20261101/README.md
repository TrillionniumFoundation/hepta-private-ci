# R15: checked planning, exact headroom and lossless evidence

This additive continuation starts from R14 commit
`ad32ceac6972e811ce74802ab5c44dc63b40bd4b`. It preserves the frozen R14 scientific
source, protocol, selected models and negative confirmation result. No new
model is fitted and no new efficacy confirmation set is opened.

## Outcomes

- All 48 original R14 tests and 22 R15 tests pass locally.
- Checked planning rejects nonfinite transitions and values across optimal and
  actual-policy interfaces. No-reset channel reporting and near-tie action
  reporting use the same semantics as execution.
- The batched common controller preserves all 19,927 reachable decisions in the
  frozen 864 actor/schedule cases. Its largest action-value difference from the
  original controller is `5.551115123125783e-16`.
- In 192 measured full executions, representing 16,384 unique actor episodes
  repeated six times, all actions, observations, fees and outcomes match. The
  four aggregate CPU reductions are 38.14%, 40.89%, 41.40% and 42.96%.
- The numerical optimal-policy headroom over fixed B is only 0.000624852 IID
  and 0.000824513 OOD. This is below the unchanged R14 mean-gain floor of 0.01.
  It diagnoses an unattainable effect size in this fixed task; it does not pass
  the original quality gate or establish a universal limit for HCSN.
- Nine oversized original ZIPs are represented by 26 genuine gzip containers.
  Original ZIP bytes, Git blobs and all 134 training/development members are
  recoverable and verified. No blob limit, spelling exclusion or scientific
  threshold is relaxed.

See [REPORT_ZH.md](REPORT_ZH.md) and [BLOCKERS.json](BLOCKERS.json) for the full
scope. The remote CI and native production qualifications remain distinct from
these local checks.

## Why batching preserves the finite objective

For a nonnegative joint state/history mass row `u`, the value is homogeneous:
`V(u) = sum(u) * V(u / sum(u))`. WAIT transports `u P`; RESET transports
`u R P`; READ transports each `u P * E[:, symbol]`. Terminal reward is linear
in joint mass. Time and reset fees are multiplied by incoming mass, and READ
fees are charged on the end-state mass. This permits batching observation
branches without changing the reward, observations or action opportunities.

`BatchedBeliefDP` batches horizons of at most three with at most eight symbols.
Longer or wider models use the checked reference recursion. Both ordinary and
HX estimators receive this common implementation. The near-tie fallback is
conservative numerical engineering, not an interval-arithmetic certificate.

## Reproduction from the prepared branch

Run from the repository root, using Python 3.12:

```bash
python -m pip install -r tools/hcsn/unified_cell_r12_20261031/requirements-numpy.txt
python -m unittest discover -s tools/hcsn/task_aligned_r14_20261101 -t .
python -m unittest discover -s tools/hcsn/continuation_r15_20261101 -t .
```

Restore the original ZIPs to a scratch directory; this leaves the checkout
clean. The frozen extractor then restores the original model files:

```bash
python -m tools.hcsn.continuation_r15_20261101.transport restore \
  --manifest tools/hcsn/continuation_r15_20261101/transport_evidence/MANIFEST.json \
  --destination /tmp/hcsn-r15-original
```

Copy `archives/TRAINING_ARCHIVES.json` from the unchanged R14 directory into
the same relative archive directory below `/tmp/hcsn-r15-original`, then run:

```bash
python -m tools.hcsn.task_aligned_r14_20261101.evidence_pack restore \
  --index /tmp/hcsn-r15-original/tools/hcsn/task_aligned_r14_20261101/archives/TRAINING_ARCHIVES.json \
  --destination /tmp/hcsn-r15-models
```

Copy the unchanged `runs/formal/FREEZE.json` into `/tmp/hcsn-r15-models/FREEZE.json`.
The original common-model and training files restored above already have their
frozen hashes. The remaining source identities are verified in the checkout.

Recompute finite-task expectations in a new output file:

```bash
python -m tools.hcsn.continuation_r15_20261101.attainability \
  --run /tmp/hcsn-r15-models --output /tmp/hcsn-r15-attainability.json
python -m tools.hcsn.continuation_r15_20261101.replay \
  --run /tmp/hcsn-r15-models --output /tmp/hcsn-r15-replay
python -m tools.hcsn.continuation_r15_20261101.audit_planner \
  --run /tmp/hcsn-r15-models \
  --reference /tmp/hcsn-r15-attainability.json \
  --replay-freeze /tmp/hcsn-r15-replay/FREEZE.json \
  --output /tmp/hcsn-r15-planner-audit.json
```

Outputs deliberately refuse to overwrite earlier results. CPU times are
machine-dependent; reconstruction is expected to preserve behavior, not timing
bytes. `evidence/ATTAINABILITY.json.gz` contains the exact original 704,496-byte
diagnostic; its small companion summary records both compressed and original
hashes. Other gzip files contain original per-episode or per-case records.

## Evidence map

| Path                                          | Evidence                                                  |
| --------------------------------------------- | --------------------------------------------------------- |
| `evidence/ATTAINABILITY_SUMMARY.json`         | Complete eight-fit finite-task ceiling                    |
| `evidence/ATTAINABILITY.json.gz`              | All 432 schedules and both actor expectations             |
| `evidence/ATTAINABILITY_REVIEW.json`          | Separate Decimal arithmetic and identity audit            |
| `evidence/PLANNER_EXHAUSTIVE.json`            | Every reachable decision in the frozen task               |
| `evidence/PLANNER_EXHAUSTIVE.records.json.gz` | All 864 checked actor/schedule cases                      |
| `evidence/replay_001/FREEZE.json`             | Source and artifact identities before timing              |
| `evidence/replay_001/SUMMARY.json`            | All 192 timed calls, summarized by domain and arm         |
| `evidence/replay_001/*.json`                  | Unselected timing repeats and actual per-call costs       |
| `evidence/replay_001/*.records.json.gz`       | Full episode traces, fees and outcomes                    |
| `transport_evidence/`                         | Original archive transport and independent reconstruction |
| `evidence/UPSTREAM_CI_AUDIT.json.gz`          | Pinned failing upstream jobs and repair scope             |

The R14 scientific source is not reformatted to satisfy unrelated style checks.
The R13 workflow change is formatting-only; the new R14/R15 workflow runs the
actual regression suites. This directory does not activate production neurons,
change Rust state ownership, claim financial FP32 acceptance, or establish
multimodal foundation-model superiority.
