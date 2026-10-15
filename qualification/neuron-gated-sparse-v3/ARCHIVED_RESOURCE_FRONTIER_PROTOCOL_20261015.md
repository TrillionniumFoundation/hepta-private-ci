# Archived Neuron Q24 resource-only frontier (2026-10-15)

**DRAFT / RESEARCH ONLY / DENY_ALL / NO_MODEL_PROMOTION**.

This additive, independently testable source-only review stacks on frozen
[#2224](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2224)
and inherits the original hosted evidence provenance documented in
[#2163](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2163).
It does not modify selected V1, the four temporal mechanisms, live Worker,
NDU authority, Cell Split, Artifact CAS, Evidence WAL, FinalUse or CNS routing.

## Exactly two successful original GitHub Actions artifacts

| Original hosted run | Exact artifact | Uploaded ZIP SHA-256 |
|---|---|---|
| [Native-trained Q24 shadow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38667249963) | 11945633077 | `9c871918e306f6f0fa0c6f3864bd75ff9271df3829ce8b58108618fc99e93995` |
| [Q24 mechanism fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38667249967) | 11945529544 | `f65886ca41941de185dd2af8bb9f05221933e9208e078889179dc5671650834b` |

Run `archived_resource_frontier.py` against these ZIPs as originally
downloaded, not substituted JSON or generated fixture receipts. The reader
checks ZIP hashes, exact member names and bounds, strict JSON keys, complete
arm/scale identities and cross-document matching costs. It independently
recounts five unique physical weight digests across 20 model file slots, and
rejects false production A0/F32 native parity/target-host status.

```sh
python qualification/neuron-gated-sparse-v3/archived_resource_frontier.py \
  --trained-zip /approved/original/native-20.zip \
  --mechanism-zip /approved/original/mechanism-fixture.zip \
  --output /new/create-only/resource-frontier-review.json
python -m unittest discover -s qualification/neuron-gated-sparse-v3 \
  -p 'test_archived_resource_frontier.py' -v
python -O -m unittest discover -s qualification/neuron-gated-sparse-v3 \
  -p 'test_archived_resource_frontier.py' -v
```

The *exact* exported report
`ARCHIVED_RESOURCE_FRONTIER_20261015.json` is a reproducible, descriptive
observation record, **not** independent authentic host attestation.
Both old hosted ZIPs may expire under original 14-day Actions retention;
do not silently replace them with reserialized JSON, a new run or a
fabricated passing fixture. Preserve originals in independently approved
artifact storage if reproducibility is needed beyond retention.

## Measured mechanism-only 4,096 logical Cell cohort

The original five arms all used eight ticks per logical Cell on the same
synthetic 32-channel trace, one arm per CI process. Values are measurements
of that mechanism-only research setup, not a shared-resident Stem fleet,
and do **not** include a real Encoder, GPU, model training, queues, WAN,
CAS, WAL, signatures, NDU decisions, recovery or target hardware SLA.

| Temporal mechanism | p99 tick (nanoseconds) | CPU process RSS (bytes) | ticks/s (reported milli-unit divided by 1,000) |
|---|---:|---:|---:|
| V1 | 164,744 | 10,883,072 | 5,619.724 |
| V2 | 205,812 | 10,907,648 | 4,585.135 |
| V3 | 352,065 | 12,566,528 | 2,802.407 |
| Diagonal SSM | 326,355 | 11,505,664 | 2,975.378 |
| Low-rank minGRU | 363,622 | 11,362,304 | 2,685.029 |

The reader defines **resource-only dominance** within one measured scale:
a candidate is dominated if another arm has p99 and RSS no greater,
tick-throughput no smaller, and at least one strict improvement. For
4,096 Cell mechanism-only records the undominated resource arm is **V1**.
Other scale outcomes differ: at 64 logical Cells the undominated set
contains V1, V2 and SSM; at 256 and 1,024 it contains V1 and V2.
This is a *descriptive, within-run resource check*, not proof that a
different Cell would be faster on target hardware.

## Distinguish physical weights, capacity, cost, and actual task value

Original trained-shadow files comprise 20 nominal four-arm/five-cap
positions, 40 fresh Rust process invocations, and only **five distinct
physical weight digests**: V2=1; V3=1; SSM=1; minGRU=2. Exact Head/Q24
integer-replay checks are not full F32/native selected-policy parity.

A true learning-cost Pareto frontier is **NOT** computed here, because
there are no independently signed, paired same-task future utility,
retention, negative-transfer and OOD outcomes for these temporal candidates
alongside their complete Encoder/Worker/Head/migration/NDU costs.
Accordingly the report contains
`complete_lifecycle_quality_cost_pareto_admissible=false`,
`production_model_promotion_permitted=false`,
`statistical_model_winner_selected=false` and `ndu_eligible=false`.

The source-only unit file has **17** methods. Its default GitHub
`test_*.py` run uses explicitly synthetic miniatures and negative
controls, not the original two archives; setting both
`HEPTA_TRAINED_Q24_ZIP` and `HEPTA_MECHANISM_Q24_ZIP` enables the
exact-archive positive test. In the local session with both original ZIPs,
**17/17** passed normally and **17/17** with `python -O`, and `compileall`
passed. GitHub-hosted exact-head green is a **separate gate**.

The tested source bytes have the following Git blob hashes:
- `archived_resource_frontier.py`: `8b2424805c2dbc5df2c1692b20533d1ac50af322`;
- `test_archived_resource_frontier.py`: `0928732cf588d5f332942d795544116d737f45f0`.

## Remaining strict dependencies

1. **A0**: independent current production Cell/model/Host owner identities,
   signed manifest/weights/head/checkpoint and frozen no-change evaluation.
2. **A1/A3**: genuinely distinct *realized* private models or a predeclared
   unequal-size quality-vs-cost design (do not rename parameter ceilings).
3. **A2**: actual pretrained shared Encoder + per-Cell Heads with source-group
   and tenant isolation; full lifecycle and separately accounted materialization.
4. **A3**: genuine prospective utility and negative-migration/future windows
   evaluated by independent NDU owner, not this report.
5. **A4**: target-host, full 64–4,096 Cell p95/p99, peak CPU/RSS/GPU/VRAM,
   energy, WAL/CAS/cutover and crash recovery.

**Never convert resource-only observations into model-promotion receipts.**
