# A3: actual physical Cell parameter budgets, not nominal ceiling labels

**Research only, stacked on Draft PR #1979 and #1884, not main.** Selected V1,
Cell Owner, NDU authority, journal, CNS route and production final-use remain
unchanged.

## The audit finding

Five ceiling labels of 2,048; 8,192; 16,384; 65,536; 262,144 private
parameters do not guarantee five actual model sizes. For the physically
saved synthetic 16-channel research models:

| Arm | Real private parameters at every ceiling | Unique shape tiers | Unique SHA |
|---|---:|---:|---:|
| V2 | 33 | 1 | 1 |
| Gated V3 | 81 | 1 | 1 |
| Diagonal SSM | 65 | 1 | 1 |
| Low-rank minGRU, rank 16 | 1,089 | 1 | 1 |

The frozen V1 baseline is selected elsewhere and was not trained here.
20 file slots contain only 4 distinct model blobs. Treating the 20 slots
as independent same-size experiments would manufacture statistical evidence.

At width 128 minGRU can use five distinct ranks and capacity profiles, but
V2, V3 and SSM still have one fixed-sized shape per width, and their realized
parameter counts remain unequal. Distinct minGRU tiers alone do not meet a
four-arm realized-size matching requirement.

## Mandatory audit

The new realized_budget_audit.py independently reopens the pinned
training-receipt.json and all 20 physically saved safetensors, using
candidate_inventory.verify_artifact for SHA, names, shapes, dtype, Q24
parameter validity, private parameter count and physical bytes. It rejects
duplicate or missing arm/ceiling slots, symlinks, changed counts, nonfinite
reported costs, width drift, silent post-training clamp and false promotion.

The versioned realized-budget-physical-audit.v2 output records all real
parameter counts, SHA-collisions across ceilings, effective independent
physical model and capacity counts, cross-arm parameter ratios, optional
untrusted per-arm CPU/optimizer claims, and explicit design blockers.

Every new 20-artifact training invocation automatically creates the
additional realized-budget-audit.json. The 20-model/40-native-process
research matrix reopens the same source files and carries a no-authority
summary of this audit into its receipt.

### Research diagnostic

    python qualification/neuron-gated-sparse-v3/realized_budget_audit.py \
      --trained-root "$TRAINED_ROOT" \
      --receipt-sha256 "$PINNED_TRAIN_RECEIPT_SHA" \
      --synthetic-canary --report "$NEW_AUDIT_REPORT"

Normal owner-scoped experiments omit the synthetic flag but must separately
obtain genuinely current, independently validated signed A0 Owner evidence.
A signed-format claim is not physical target-host execution.

### Strict five-tier same-realized-parameter design gate

    python qualification/neuron-gated-sparse-v3/realized_budget_audit.py \
      --trained-root "$TRAINED_ROOT" \
      --receipt-sha256 "$PINNED_TRAIN_RECEIPT_SHA" \
      --synthetic-canary \
      --require-five-tier-matched-design \
      --report "$NEW_STRICT_REPORT"

This exits 2 **after persisting the audit** unless each of the four arms
has five distinct physical weight SHA values, five different actual capacity
profiles and exactly equal realized private parameter counts across all four
arms within each nominal ceiling. Existing width-16 fixtures are BLOCKED.

A diagnostic test that correctly observes BLOCKED is not an approval of a
five-tier learning experiment. The audit always retains
same_size_head_to_head_quality_claim_admissible=false,
matched_training_compute_independently_verified=false,
ndu_eligible=false, production_qualification=false and NO_MODEL_PROMOTION.

## Scientific next steps

Use actual physical parameters/bytes, rank, private Head and projection
weights, state and optimizer bytes, target CPU/GPU budget, real elapsed
training FLOPs and common independent case windows. Never count two
ceilings with identical physical model bytes as two independent trained
replications. Do not pad unused private tensors merely to fake size
equality. If an arm cannot reach comparable sizes at the shared width,
report the actual cost-quality Pareto frontier instead of a false strict
equal-parameter trial.

Only a genuine selected-Owner A0, native Q24 replay and measured independent
prospective future/OOD NDU outcome, signed finalized control and 64/256/
1024/4096 Cell target-host physical A4 allow further production review.

## Source tests

    python -m unittest discover \
      -s qualification/neuron-gated-sparse-v3 \
      -p test_realized_budget_audit.py -v

Fifteen synthetic actual-byte tests cover false five-tier claims, 128-wide
rank variation, tampered safetensors, training/cost identity changes and
strict gate exit code 2. This is not evidence of model superiority.
