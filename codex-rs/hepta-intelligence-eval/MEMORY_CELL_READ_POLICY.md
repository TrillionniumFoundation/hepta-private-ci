# Learned read policy in the existing source-write experiment

This extension follows the controlled event reader and source-only knowledge
module. It adds the missing learned-read comparison, not a new production store
or acceptance boundary. The inherited five-arm mode remains available unchanged
when no policy argument is supplied. No human-reviewed capability gate is waived.

## Fixed source, reader and independent interventions

Ten scalar weights learn next-event ranking from the existing controlled source
schema. Only the eight previously declared calibration scopes contribute labels
or gradients. Training derives one-/two-hop relation paths from those past source
records and explicit correction closure; it does not open task plans, future
questions or answer labels. Unresolved or conflicting paths are unknown, not
arbitrary positives or negatives. The lookup grammar is explicit and bounded;
this is not a learned natural-language parser or proof of semantic sufficiency.

Every score uses the same ten features: entity/path match, effective logical
revision, explicit replacement status, their interaction, candidate position and
traversal state. An initial policy retains the retrieval rank; a learned policy
uses the same feature function. These two arms isolate weight learning from
feature engineering. The calibrated hybrid and deterministic organized controls
remain in the experiment. Learning must outperform those controls, not merely a
weak initialization, before claiming a useful learned read path.

Training makes 192 bounded float64 updates with a source-scope-balanced schedule.
Each path stage is supervised only by the controlled original relations. Candidate
order is varied without using labels; raw targets never enter feature vectors.
The JSON policy binds the exact training sources, source dependencies, calibration
scopes and reader identity. It is frozen in a separate process before the reader
opens task payloads. Test scopes and roots must be disjoint from policy training.
This is a previously authored development environment, not a prospective calendar
sample, independent human supervision or a generalization certificate.

Seven arms now share the same reader, decoder and candidate pools:

- calibrated hybrid / base;
- deterministic event organization / base;
- same organized evidence / source-written knowledge adapter;
- parameter-only / same knowledge adapter;
- empty / base;
- initial read policy / base;
- trained read policy / base.

The knowledge-vs-organized comparison requires identical actual prompt tokens and
evidence. The learned-policy comparison changes only policy weights; sequential
states may subsequently differ and are recorded. No out-of-pool evidence is
inserted. No model-generated answer is repaired or supplied from policy targets.
All three baseline, policy and module paths use the same fixed procedural worker.

## Costs and interpretation

Retain source extraction/index cost, knowledge writing, policy projection/training,
actual selection work, model tokens/time, storage and procedural execution. Count
reference corpus bytes once when calculating a combined total. Query operation
estimates are not FLOPs. Deployed maintenance, real retention and cross-host
recovery are unknown, so total production lifecycle cost stays null.

A policy's support-document hit does not prove answer correctness or citation
entailment. Source-only supervision can be effective on the explicit schema while
failing on natural history. Logical revisions, process restarts and repetitions
do not create three independently admitted snapshots or two future time windows.
Neither this policy nor the knowledge adapter can promote itself.

## Execute

The existing `hepta-memory-write-experiment.yml` runs all regressions, repository
formatting, actual pretrained source writing, small-policy training, and a new
process for all seven model arms. Older outputs remain tied to their source.
The local command is:

```sh
python scripts/memory_cell/experience_policy.py SOURCES.json CALIBRATION_SCOPES.json POLICY.json --source-sha SOURCE_SHA --scopes-sha SCOPES_SHA --reader-identity EXACT_READER_ID
python scripts/memory_cell/experience_write_trial.py read PLAN INPUTS MODEL SNAPSHOT NEW_OUTPUT --plan-sha PLAN_SHA --stage-sha STAGE_SHA --ready-sha READY_SHA --policy POLICY.json --policy-sha POLICY_SHA
```

The policy command consumes no QA labels. The reader revalidates the external
policy pin and source lineage. Missing or failed model calls stay in the original
complete census. Tests using small tensors or model substitutes are explicitly
mechanism tests; only the separate pretrained run can supply task results.
