# A3 realized-private-budget audit — shadow, fail-closed

This strictly additive, **read-only** research gate extends Draft PR #1979
(which itself stacks on frozen PR #1884); it does not merge or alter `main`,
selected V1, model routing, CAS, CNS, NDU or final-use authority.

## Why a five-tier model experiment can be a one-tier experiment

A budget is a **maximum allowed private parameter count**, not proof that
a candidate has that number of parameters, distinct learning capacity or
a different physical weight checkpoint. Counting source branches, filenames
or ceiling labels as independent model variants is scientifically invalid.

The reference 16-coordinate synthetic fixture has four arms and five tiers
(2K, 8K, 16K, 64K, 262K), but physical SHA and tensor parsing show:

| Arm | Actual private parameters | Effective capacity variants | Distinct weight SHAs |
| --- | ---: | ---: | ---: |
| V2 | 33 | 1 | 1 |
| Gated V3 | 81 | 1 | 1 |
| Diagonal SSM | 65 | 1 | 1 |
| Low-rank minGRU | 1,089 | 1 | 1 |

Thus **20 nominal candidate file slots only contain four unique physical
weight contents**, and none of the four candidates have matching realized
parameter counts at any nominal ceiling. This is a synthetic plumbing canary,
not a fair same-size efficacy experiment. A larger 128-coordinate synthetic
counterexample produces five distinct minGRU ranks while V2/V3/SSM still
remain fixed-capacity, proving that a parameter ceiling alone cannot establish
equal-sized models across architectures.

## Executable gate

`realized_budget_audit.py`:
- Pins a physical `training-receipt.json` by SHA256, rejects duplicate JSON
  keys, nonfinite JSON, missing/duplicate arm/budget slots and mixed Cell width;
- Independently reopens **all 20** bounded physical safetensors, checks exact
  tensor names, shapes, datatypes, content hash, parameter count and Q24
  admissibility through `candidate_inventory.verify_artifact`;
- Rejects symlink paths, mismatched optimizer-step declarations, incorrect
  published private budget ceilings, forged production/NDUs;
- Separately counts unique parameter/rank/width capacity shapes and unique
  physical SHA256 values, along with cap utilization and within-tier realized
  parameter-count equality;
- Always emits `same_size_head_to_head_quality_claim_admissible=false`,
  `production_qualification=false`, `ndu_eligible=false`, and
  `NO_MODEL_PROMOTION`. No measured future labels or real Owner evidence are
  manufactured.

Run on an **explicit** synthetic fixture:

    python qualification/neuron-gated-sparse-v3/realized_budget_audit.py \
      --trained-root /path/to/canary/ \
      --receipt-sha256 "$PINNED_RECEIPT_SHA256" \
      --synthetic-canary \
      --report /review/nonproduction-budget-realization.json

Historical local fixtures lacking the v1 `evidence_class` can only use
`--synthetic-canary --allow-legacy-fixture`; this option is not for CI
promotion or authenticating a deployed Cell. For a signed-A0-format study,
omit the synthetic flags, but the tool still **does not authenticate** a
trusted Owner or live model execution. Actual A0, signed future NDU and
target-host A4 must be independently established.

`run_native_physical_matrix.py` now attaches this physically computed audit
to its native receipt. The physical CI explicitly asserts all 20 artifact
slots exist while rejecting any same-size or production inference. The
additional `test_realized_budget_audit.py` includes real synthetically
serialized safetensors bytes and tests for duplicated caps, missing artifacts,
same-count geometry errors, changed receipt SHA, mixed inputs, forged
authority and a genuinely five-rank minGRU width-128 counterexample.

## Scientific requirement before declaring model superiority

Preregister model budget *on actually loaded private tensors*, optimizer
states and runtime memory, training compute/FLOPs/tuning schedule, Encoder and
request feature snapshots. For each arm/tier, disclose:
- realized private trainable parameters, frozen private projection and Head,
  actual physical bytes, optimizer state and Checkpoint memory;
- paired future task utility including OOD, calibration, selective-coverage/
  abstention cost, negative transfer and uncertainty clustered by Cell;
- target-host full end-to-end resource use, including CAS/signature/WAL and
  recovery, not only sparse-kernel timing.

Do **not** introduce meaningless dummy parameters to make size totals match.
Compare a predeclared cost-quality Pareto frontier, and reserve phrases such
as “at the same size” for genuinely matched active private parameter/resource
budgets. Production and NDU promotion remain prohibited without independent
Evaluator, Selector, Executor and final-use gates.

**NO_PRODUCTION_PROMOTION. NO_MAIN_CHANGE.**
