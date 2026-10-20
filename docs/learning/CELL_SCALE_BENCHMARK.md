# Cell scale and topology lifecycle benchmark

This is the executable qualification contract for the six cell scales in
`CELL_EXECUTION_BENCHMARK_MATRIX.json`. Run the plan/manifest validator with:

```bash
python3 qa/meta-network-scale/scale_matrix.py plan
python3 qa/meta-network-scale/scale_matrix.py validate result.json
python3 -m unittest qa/meta-network-scale/test_scale_matrix.py
```

The validator checks that a result manifest includes all comparison arms, future
window and negative-transfer evidence, lesion/ablation, crash/reopen, stale
generation rejection, rollback and resource metrics. It does not calculate
utility, prove a scaling law, or admit a production topology.

## P4 lifecycle mapping

| Required step | Existing owner to exercise | Failure disposition |
| --- | --- | --- |
| candidate | `hepta-plasticity::TopologyProposalV2` | reject proposal |
| independent evaluation | `TopologyProposalV2.evaluator_id` plus evaluation digest | reject self-evaluation |
| selector | external selector/acceptance boundary | no signed snapshot |
| signed successor snapshot | `DurableTopologyProposalRegistryV1` | preserve predecessor |
| state migration | `WriterHandoffPlanV1` and runtime migration owner | reconcile then rollback |
| old writer fence | supervisor writer-handoff journal | never allow dual writer |
| route cutover | `hepta-runtime::topology_execution` | rollback predecessor |
| canary | `StructuralCanaryControllerV1` | abort or quarantine |
| rollback rehearsal | canary rollback witness | quarantine if witness fails |
| production admission | external operator/release boundary | no automatic admission |

The fault matrix in `hepta-plasticity::topology_fault_scenarios_v1` covers
split, merge, rewire and retire at every step. The external scale harness uses
those scenarios as required labels; it does not replace the runtime owners.

## Interpretation

Compare no-change and fixed-routing baselines before interpreting learned routing.
Compare shared and duplicated encoders at equal resource budgets. Report
expressivity, learnability, unseen-task adaptation and resource scaling as
separate claims with uncertainty intervals. Cell count alone is not evidence of
a general-purpose agent.
