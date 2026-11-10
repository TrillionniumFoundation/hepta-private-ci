# 1 + 2 + 7: frozen Cell-lineage scope gate (research only)

**Base:** `hepta-private-ci` draft PR #5569 head `374af2c7b28c76e3ebf1e3a90593389c8f6f7bd0`.
**Posture:** `REVIEW_ONLY / HOLD_NO_GO / NoUpdate`. This patch is not an ordinary daemon bootstrap, production registry, authenticated evaluator, production adoption or performance qualification.

## Why this increment

There is already a bounded `Component` / `CellOwner` lifecycle, semantic producer with private heads, GRU/diagonal-temporal producer, byte-bound Q24 base/organ/cell composition, and native generation/Reset checks. Creating another runtime or claiming a generic multimodal ABI would repeat or overstate those mechanisms. Existing ORG-1 split/merge/rewire tests are structural: 99 task pairs, zero training steps, and unknown full resource costs; scientific admission remains HOLD.

This patch introduces a **pure Python, fail-closed, read-only enrollment/update reviewer** on top of the experimental producer family. It does not duplicate native bundle serialization or effect authority.

## Frozen example

| Responsibility | Initial example kernel | Initial update posture |
| --- | --- | --- |
| PERC | frozen shared semantic features + private readout | frozen |
| MEM | frozen semantic features + independent state/RAG | frozen |
| PRED | GRU causal temporal state | `kernel_and_heads` (research only) |
| CTRL | temporal critic/control + deterministic action gate | frozen |
| VERIFY | frozen shared features + private checker-risk head | `heads` (research only) |
| ACT | temporal skill state + deterministic effect owner | frozen |
| LEARN | original training/evaluation/selection owner orchestration | frozen deterministic |

This is a **configuration example**, not a universal kernel assignment: actual Cell enrollment accepts other lineage/kernel pairings with explicit valid update scopes, except that initial LEARN remains a deterministic orchestrator. At most three *instances* may be simultaneously trainable; the others remain frozen. Seven means functional responsibilities, not neural architectures or an upper bound on instances.

`CellRoster` requires all seven responsibilities, distinct principal/agent/cell/run state partitions and exact base/organ/encoder/tokenizer/normalizer/composition/numeric-profile alignment for any shared semantic feature group. Such a group also requires one matching state owner and data-use scope: it never grants cross-principal/agent/data residency or temporal state sharing by implication. A group now additionally requires a nonzero SHA-256 `feature_abi` declaration for the frozen feature dimension, layout and interpretation, with exact equality across participating cells; a digest declaration is **not** a native ABI attestation. Nonparticipants must leave it absent.

`review_update` binds original bundle digest/generation, a nonzero training dataset SHA-256 pinned **at trainable enrollment** (not selected or relabelled by the later candidate), training source, frozen update rule, frozen evaluation profile, permitted component changes, optimizer step ceiling (strict integer zero for frozen cells and unsigned-64-bit next-generation bounds), and a non-omittable cost-axis inventory. Frozen Cells cannot carry a training dataset commitment. These are caller-supplied claims, not proof of dataset bytes, provenance, or data rights. Unknown cost or absent original evaluation receipt keeps HOLD. Even with all declared fields present, its only positive status is `REVIEW_ONLY`: a digest is not authentic execution evidence, real model loading, independent data, held-out outcomes or acceptance.

## Non-authority and open blockers

- Q24 factor graphs are not a generic linear/LoRA ABI. Exact roundoff semantics and backend pins still need native validation.
- This reviewer cannot authenticate `CellCompatibilityBundleV1` bytes, model/data provenance, source permissions, signed original Evaluation, native rollback lineage, recovered state or the runtime owner.
- `REVIEW_ONLY` never authorizes installation, effects, a split/merge, or an Adopt decision. No new production path or capability is created.
- GRU remains the default temporal reference. Diagonal SSM, CfC, attention and HCSN must be compared with matched tasks, information, training/tuning opportunities, gradient/stability/recovery checks, resource costs, independent outcomes and old-task retention. HCSN is not upstream of seven-lineage development.

## Focused reference tests

```sh
python3 -m unittest discover -s scripts -p 'test_hepta_cells_lineage_policy.py' -v
python3 -m py_compile scripts/hepta_cells/lineage_policy.py scripts/test_hepta_cells_lineage_policy.py
```

The isolated Python 3.13.5 reference run covered 15 methods and passed 15/15 after correcting a *test message expectation* found in the first run. It exercises seven-lineage coverage, two trainable points, isolated instances, cross-principal/binding refusals, no temporal pool sharing, illegal learning scopes, stale generations/rules, forbidden changed weights, unknown/invalid cost axes, and non-authorization. This is **not** the source-head native `just test`, Windows/macOS, required CI or a real-task scientific comparison.

## Required progression

1. Bind the declaration to the original authenticated native Bundle/Cell owner and frozen model/data/configuration byte identities. Do not introduce a second authoritative selector.
2. Run independent real-task PRED (GRU and matched controls) and VERIFY (risk-only versus effective real checks) trials with complete episode/cost denominators and signed original evaluation.
3. Compare no-learning, shared updating readouts, and private readouts under equal information and compute. Only consider a third trainable instance after retention/negative-transfer and measured net-benefit tests.
4. Reuse the existing ORG-1 topology/rollback protocol for split/merge/rewire and require complete resource metering and independent held-out benefit. Redundant subtypes should be eligible for merging.
5. Run the unchanged head's relevant Python, native, platform, formatting, and required CI checks. Record rather than erase failures.

**Local interface conformance may be PASS while scientific and production acceptance remain HOLD.**

## Follow-up: exact-head CI and fail-closed bounds (2026-11-10)

On original #5724 HEAD `176140c8c4f17204e704a8e9e4ae758f3567fa59`, the hosted Codespell job [129849880971](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42822082209/job/129849880971) failed while scanning two **binary** `raw-all-model.tar.gz.part*` fragments from inherited qualification evidence. The follow-up restricts the spelling skip to these named compressed shards; it neither deletes immutable evidence nor excludes Python/Rust/docs, changes a required check, or claims a passing CI run.

The follow-up also adds three independent reference test methods (18 total), rejecting missing/mismatched claimed feature ABI, false/float/None training step budgets on frozen cells and generation overflow. The native Bundle owner must still verify that the claimed feature ABI matches real dimensions, encoding and numerical semantics. Retest the actual PR source with the named Python commands and read new Actions results. CI and production/science status remain HOLD until verified.
