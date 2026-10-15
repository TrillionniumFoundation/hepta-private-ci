# Cross-Fact Granite97 Reader: executable next campaign (2026-10-15)

**Status: DRAFT / RESEARCH_ONLY / DENY_ALL / no model winner.**

This child of the actual V5 Reader stack reuses the original immutable Granite97 token feature bank and V5 source, weight, cache, and training-case identities. No backbone or selected production inference model is updated.

## What runs

- `cross_fact_granite_campaign.py`: new full-budget real-token campaign. Requires the already staged original V4/V5 source data, pinned model snapshot, cached train features, prior V4 design/native freeze and V5 design, all outside the checkout. The source can load the frozen Encoder through the existing exact-identity TokenBank; it is **not** a replacement Encoder implementation.
- Two equally parameterized H=32 Reader arms: masked **cross-fact** attention residual versus equally sized **fact-local** MLP; each adds exactly **4,096 trainable parameters** on top of the original Reader, with identical initial weight bytes and six-input inference API.
- Three seeds **41, 47, 53**, 8,000 max Adam updates per arm, 16 training cases per step, complete four-row paired worlds, three recurrent hops, learning rate .001, pair weight .5 and diagnostic interval 250. Both arms inherit the original train-only stop gate: all 128 candidates correct, both evidence worlds correct and logit CE <= .10.
- `cross_fact_granite_review.py`: separate stdlib-only reviewer. Recomputes TRAIN symbolic truth and saved probability success, rehashes training/model files and source, checks matched initialization, parameter count, optimizer exposures, schedule identity, and rejects incomplete cohorts or unexpected fresh evaluation after a failed train gate. It cannot independently attest clock accuracy or physical Encoder execution.
- The campaign **cannot encode fresh test-role cases until all six fitted arms pass the frozen full-fit gate AND per-seed actual training updates, exposures, optimizer-state bytes, model parameter counts and original schedule SHA match between arms**. Unequal arithmetic/FLOPs remain explicitly unproven. The original V5 protocol factory constructs candidate definitions earlier; only TRAIN cases are used in optimization.
- If any fit fails, retain six training receipts with `train_gate_failed_no_fresh_scoring`. If all fits pass but work investment differs, reject with `unequal_actual_budgets_no_fresh_scoring`. Only when both hold, freeze every artifact and **seal twelve complete inference prediction panels without computing labels or writing scores**. In a separate Python process, `cross_fact_granite_score.py` checks all twelve seals and frozen Head digests before importing fresh-domain scoring labels, then writes 12 write-once scores plus one completion manifest. Source/label OS isolation and independent host attestation are NOT claimed.

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

# First inspect training gates and twelve sealed prediction panels:
python -S qualification/stem-cell-v1/cross_fact_granite_review.py \
  /independent-storage/cross-fact-granite-v1

# ONLY when all six fits, actual budget comparisons and twelve seals pass:
python qualification/stem-cell-v1/cross_fact_granite_score.py \
  /independent-storage/cross-fact-granite-v1

# Independently replay original scoring and proof-file identities:
python -S qualification/stem-cell-v1/cross_fact_granite_review.py \
  /independent-storage/cross-fact-granite-v1
```

**Note:** `python -S` is appropriate for the pure-stdlib reviewer only if the original project libraries and their imports are locally available. It must not be used for the PyTorch campaign. Output directories cannot preexist, avoiding accidental overwrite of evidence.

## Executed checks in this authoring environment

The newly extended source plus the five focused suites were exercised against the exact inherited original TokenReader: **30/30 local tests in ordinary Python and 30/30 under `python -O`**, including sealed-to-score end-to-end fixtures, no-label-before-gate, full prelabel source roster checks, synthetic autograd and budget parity/adversarial file tests. The pinned original Encoder was NOT run by these suites. Remote exact-head CI has not completed, and a source hash alone is not independent execution proof. The Granite campaign itself **has not loaded real weights or run six pretrained fits** here: only a synthetic earlier paired-world prototype completed. Neither natural-task ability, equal-FLOP advantage, fresh generalization, NDU efficiency, a 4096 Cell physical runtime nor production readiness is asserted.

## Selection gates

Do not interpret a gate PASS, trained Head or fast batch as authority to load or serve a model. Keep the original negative V5 results and previous static/Split/NDU results. Require source-disjoint external tasks, exact-head native qualification, independent original-label scoring, old-task retention, full Encoder+training+online cost and target-host p99 before considering a model change. Sampled rows per logical group are not independent fresh worlds, and equal parameter count does not imply equal arithmetic.

## Reviewer semantics
- The stdlib-only reviewer accepts **three** sealed states: no fresh files after failed fitting, all prelabel predictions sealed and **not yet scored**, or all twelve scored files with a matching write-once scoring-completion manifest.
- Any partial scoring, modified seal, duplicate JSON key, symlinked evidence, wrong model digest, missing batch identity or tampered training budget fails closed.
- The original `full_fit_gate` and `matching_training_budgets` are separate facts; only their conjunction opens the fresh seal phase. This is matched *observed update/exposure/optimizer storage*, **not** equal GPU/CPU floating-point operations.

## Strict prelabel roster identity

The training entrypoint now freezes a SHA256 of each of the two original V5 fresh-domain case-ID rosters in `plan.json`, with **no labels** included. In the separate score process, `check_prelabel_seals` first checks complete fitted-model and resource budgets, all 12 sealed prediction files, 128 unique IDs per role, exact original roster digests, ordered physical batch receipts and frozen Head material. Only *after* that full check does it import the fresh-domain scoring protocol. The independent stdlib reviewer reconstructs the rosters again and rejects any changed source membership.

This is deterministic process-stage separation, **not** independently signed label custody, a trusted execution environment, or an empirical claim of source-disjoint natural-task superiority. Any prior failed fit or mismatched optimizer storage must keep outcome scoring unopened.
