# Cross-Fact Granite97 Reader: executable next campaign (2026-10-15)

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / no model winner.**

This child of the actual V5 Reader stack reuses the original immutable Granite97 token feature bank and V5 source, weight, cache, and training-case identities. No backbone or selected production inference model is updated.

## What runs

- `cross_fact_granite_campaign.py`: new full-budget real-token campaign. Requires the already staged original V4/V5 source data, pinned model snapshot, cached train features, prior V4 design/native freeze and V5 design, all outside the checkout. The source can load the frozen Encoder through the existing exact-identity TokenBank; it is **not** a replacement Encoder implementation.
- Two equally parameterized H=32 Reader arms: masked **cross-fact** attention residual versus equally sized **fact-local** MLP; each adds exactly **4,096 trainable parameters** on top of the original Reader, with identical initial weight bytes and six-input inference API.
- Three seeds **41, 47, 53**, 8,000 max Adam updates per arm, 16 training cases per step, complete four-row paired worlds, three recurrent hops, learning rate .001, pair weight .5 and diagnostic interval 250. Both arms inherit the original train-only stop gate: all 128 candidates correct, both evidence worlds correct and logit CE <= .10.
- `cross_fact_granite_review.py`: separate stdlib-only reviewer. Recomputes TRAIN symbolic truth and saved probability success, rehashes training/model files and source, checks matched initialization, parameter count, optimizer exposures, schedule identity, and rejects incomplete cohorts or unexpected fresh evaluation after a failed train gate. It cannot independently attest clock accuracy or physical Encoder execution.
- The campaign **does not encode or score fresh test-role cases until all six fitted arms pass the frozen full-fit gate**. The original V5 protocol factory constructs candidate case definitions in preparation; only TRAIN cases are used in optimization.
- If a gate fails, retain six training receipts and report `train_gate_failed_no_fresh_scoring`, not an invented generalization score. If all pass, freeze every artifact **before** `fresh_combinations` and `fresh_vocabulary` features/labels are scored, with sealed pre-score probabilities and physical inference cost receipts.

## Run against actual pinned V5 inputs

Use the identical environment, licensed inputs and immutable archive paths described in `BINDING_V5_PROTOCOL.md` and `READER_MULTIRC_V3_RUNBOOK_20261015.md`. Paths below are placeholders for **already staged, verified inputs**; the command does not download or invent them. Keep output outside the Git checkout.

```bash
cd /path/to/hepta-private-ci
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/cross_fact_granite_campaign.py \
  --source /verified/MultiRC/source \
  --snapshot /verified/Granite97/snapshot \
  --prepared /verified/V4/prepared \
  --previous-main /verified/V4/main \
  --previous-native /verified/V4/native \
  --output-v5 /verified/V5/design-and-previous-observations \
  --output /independent-storage/cross-fact-granite-v1 \
  --seed all --steps 8000

python -S qualification/stem-cell-v1/cross_fact_granite_review.py \
  /independent-storage/cross-fact-granite-v1
```

**Note:** `python -S` is appropriate for the pure-stdlib reviewer only if the original project libraries and their imports are locally available. It must not be used for the PyTorch campaign. Output directories cannot preexist, avoiding accidental overwrite of evidence.

## Executed checks in this authoring environment

The uploaded new Granite campaign/review source is byte-equal to locally tested files (Git blob identities verified). All four new/retained pilot suites completed under normal and `-O` execution: **20/20 local tests each mode**, no skips, including a real synthetic-tensor Reader backward/optimizer test and stdlib-only Granite gates/receipt negative controls. The Granite campaign itself **has not loaded real weights or run six pretrained fits** here: only a synthetic earlier paired-world prototype completed. Neither natural-task ability, equal-FLOP advantage, fresh generalization, NDU efficiency, a 4096 Cell physical runtime nor production readiness is asserted.

## Selection gates

Do not interpret a gate PASS, trained Head or fast batch as authority to load or serve a model. Keep the original negative V5 results and previous static/Split/NDU results. Require source-disjoint external tasks, exact-head native qualification, independent original-label scoring, old-task retention, full Encoder+training+online cost and target-host p99 before considering a model change. Sampled rows per logical group are not independent fresh worlds, and equal parameter count does not imply equal arithmetic.
