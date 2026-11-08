# ORG-1 structural candidate reference

## Result

The engineering slice is implemented and exercised. Scientific acceptance and
production adoption remain **HOLD / NoUpdate**. This change adds no native
activation path and does not advance the existing S4 research stage.

The final Python reference executed 99 paired tasks, or 198 arm/task executions:

| Operation | Fixed nodes | Candidate nodes | Paired tasks | Fixed / candidate score | Fixed / candidate messages |
| --- | --- | --- | --- | --- | --- |
| Split | 2 to 2 | 2 to 3 | 33 | 33/33 and 33/33 | 36 / 36 |
| Merge | 3 to 3 | 3 to 2 | 33 | 33/33 and 33/33 | 36 / 36 |
| Rewire | 2 to 2 | 2 to 2 | 33 | 33/33 and 33/33 | 36 / 69 |

Each operation contains 24 ordinary, 6 old-capability retention and 3 deliberately
selected lost-ACK recovery cases per arm. The recovery panel is a test obligation,
not an estimate of production fault frequency. Seed labels repeat deterministic
panels; they are not independent training fits. There are zero training steps and
zero organization-search candidates evaluated.

Both arms use the same dictionary-indexed router. In this bounded key/value task,
the fixed graph already achieves full correctness. Structural execution alone
therefore provides no observed quality improvement. Rewiring sends additional
messages without improving the measured score. Unknown full costs prevent a
qualified net-benefit estimate; `mean_net_gain` remains null in the real runs.

`RESULTS.json` contains the observed resource vectors and exact protocol hashes.
`ARTIFACTS.json` binds the three archives containing the original files. An archive
includes protocol, source identity, before/after graph and state, migration,
failure scene, rollback, successor trace, per-task observations and all cost rows.

## Implementation and reuse

The source parent is
`6736d8acaf3f8c69288ce6c59a7d5246ea00448f` (the existing causal D evidence work).
The original D validator and its tests are unchanged. The new files are:

- `scripts/ndu_real_runtime/organization_policy.py`: deterministic finite-panel review.
- `organization_artifacts.py`: bounded, descriptor-relative original-artifact reads.
- `organization_review.py`: read-only CLI.
- `organization_reference.py` and `organization_reference_artifacts.py`: actual
  Python state operations and create-only reference evidence.
- `test_organization_policy.py`: 22 adversarial test methods.
- `.github/workflows/hepta-cell-organization-reference.yml`: exact-source CI,
  40 regression methods and three operation runs, preserving scientific HOLD.

The original native topology proposal, migration-owner, writer-fence, governed
apply/recovery and Cell lifecycle mechanisms remain the authority boundary. This
reference does not duplicate or bypass them. Differentiation can be investigated
as a split; trainable specialization is not implemented by these key/value tasks.
Sleep and retirement are explicitly unsupported by this reviewer.

## Candidate proposal is separate from adoption

The protocol and all experiment arms bind the same scheduler, tuning contract,
objective, evaluation contract, initial graph/state and protected-capability
inventory. A supplied protocol hash checks identity; it does not authenticate
the caller or prove prospective registration. A scheduler hash checks sameness;
it does not establish that the scheduler is a qualified strong baseline.

Proposal triggers require repeated, nonoverlapping observation windows with
distinct sample identities and frozen support/effect thresholds:

| Trigger | Reference check | Remaining evidence boundary |
| --- | --- | --- |
| Stable cluster | Same cluster identity and threshold in every window | Cluster quality is an externally reported diagnostic, not learned or independently authenticated here |
| Learning interference | Recompute paired control-minus-updated held-out scores and bind the intervention | Arrays do not independently establish a causal training intervention |
| Capacity bottleneck | Recompute measured usage / capacity | The runner uses a declared logical record limit, not a measured hardware bottleneck |
| Specialization | Repeated reported call/quality benefit above the frozen threshold | A forecast only supports proposing a candidate |

Low utilization is not a supported trigger. No trigger grants execution,
retirement or adoption rights. Positive synthetic fixtures only produce
`REFERENCE_CONSISTENT`; even that result retains `NoUpdate`, scientific HOLD and
false authority flags.

## Paired benefit, complete denominators and costs

The fixed protocol supplies the task roster. Every trial and cost original binds
its arm, run ID and protocol hash, so exchanging genuine original files between
arms cannot reverse the apparent result. Task/seed duplicates, missing attempts,
unresolved outcomes and changed scheduler or initial-state identities block review.
Failed, timed-out and cancelled ordinary trials retain their planned denominator
and receive zero success credit; their costs cannot disappear. Both arms must
complete retention cases. Two failures do not prove that an old capability survived.

Ten explicit cost stages are required: search, training, evaluation, inference,
communication, loading, migration, relearning, maintenance and recovery.
The required resource axes are cumulative CPU seconds, accelerator seconds,
transferred bytes and resident byte-seconds. Energy and monetary charges can be
additional frozen axes. Physical units remain separate until the protocol's
declared utility conversion; per-axis budgets also apply. Duplicate events,
unknown axes, negative/nonfinite values and omitted stages are rejected or HOLD.
Known CPU and message-byte observations from D are lower bounds on the new ledger.

The descriptive score charges all recorded costs to the actual fixed panel:

```text
mean_net_gain = mean(candidate ordinary score - fixed ordinary score)
              - (candidate converted cost - fixed converted cost)
                / number of ordinary pairs
```

It must be strictly above the frozen practical-gain threshold, with the retention
and protected-capability checks also passing. No estimated future task horizon is
used to amortize migration or construction costs. This is a finite-panel screen,
not a confidence bound, an independence proof or a scientific adoption decision.

In the real reference runs, resident-byte integrals, energy and provider charges
are unknown. Post-meter receipt serialization and full dependency/runtime costs
are not complete. Unknowns remain null, even when a utility rate is zero. D remains
BLOCKED and ORG-1 remains HOLD; the module never certifies complete physical cost.

## Recovery capabilities and state changes

Protection follows capability identities such as `recovery:lost_ack`, not Cell
names. Every capability in the pinned inventory needs a matching fault panel,
successful completion, a minimum score and a bounded score drop. Renaming or
merging a Cell cannot remove an inventory obligation. Ordinary task gains cannot
compensate for a failed protected capability. Inventory completeness is not
authenticated by this reviewer and remains an explicit external requirement.

The runner moves 12 actual logical key/value items, checks unique key owners and
unchanged values during migration, and executes subsequent tasks through the
installed graph. Lost-ACK cases replay the same request identity and check that
the value changes once. Rewire tasks actually use the new return edge.

For the fixed arm, an injected dispatch failure changes a temporary state and
persists it before failing, while the graph stays unchanged. The dynamic arm
fails after the first persisted key transfer or edge change. Each then restores
and rereads the original graph/state bytes. The selection policy is frozen and
bound to both D recovery contracts. These are different mechanism demonstrations,
not a shared physical fault distribution. They prove recovery only at the tested
points; separate file replacements are not atomic multi-Cell adoption, and this
does not establish arbitrary-crash or external-effect recovery semantics.

## Reproduce

From the repository root, using Python 3.10+ on Linux (the retained run used
Python 3.12.14; Windows was not qualified):

```bash
python3 -B -m unittest \
  scripts.ndu_real_runtime.test_organization_policy \
  scripts.ndu_real_runtime.test_causal_topology \
  scripts.ndu_real_runtime.test_causal_protocol -v

python3 -B -m scripts.ndu_real_runtime.organization_reference --operation split --output /tmp/org1-new/split
python3 -B -m scripts.ndu_real_runtime.organization_reference --operation merge --output /tmp/org1-new/merge
python3 -B -m scripts.ndu_real_runtime.organization_reference --operation rewire --output /tmp/org1-new/rewire
```

Each leaf output directory must be absent. Runner exit zero means reference
execution completed; it does not mean qualification passed. The separate review
CLI exits 2 for HOLD. Never supply a self-generated owner hash as an independent
trusted observer to change the result.

## Remaining S4 evidence

1. Bind actual native owner execution, independent evaluator observations,
   complete initial artifacts and successor consumption to one frozen candidate.
2. Establish the fixed graph's scheduler strength with actual tuning/evaluation
   evidence and matched opportunities, not its label.
3. Run representative task clusters with independent fits and an appropriately
   frozen statistical design; include interference and capacity stress cases.
4. Complete measurement of loading, communication, migration, relearning,
   maintenance, failures and recovery, including the currently unknown resources.
5. Exercise broader native failure points and prove that the full critical
   capability inventory survives. Only the existing native owner can authorize
   adoption after these requirements are met.
