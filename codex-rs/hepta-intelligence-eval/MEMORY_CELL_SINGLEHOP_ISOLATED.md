# MemoryCell source-only single-hop control, matched to isolated two-hop trial

This registered control branches from exactly the same parent implementation `ac79f80daa6bf8d823739d35ad6af40bfb472db8` as the isolated two-hop experiment at `bd74aebc9a346bf7e8a6dc04e0abfae1816d117d`, instead of using the historical single-hop execution from an older source commit.

The hypothesis, generation baseline and eight pre-exposed controlled tasks are registered BEFORE either new answer stream is observed. Original source archive: artifact 11669174727, outer SHA256 23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b. Source JSON SHA256 35756b456f75718cc422d8678ec7ae97790ca36ced625501d24884698fddab24. Same publisher-pinned Qwen2.5-3B, same reader profile, original full-vocabulary completion-only loss, learning rate 0.0002, rank-4 q/v LoRA, 128-update and 65,536-input-token ceilings, read policy, task plan, final seven-arm reader, token budgets and bounded procedure verifier.

Only the **source curriculum** differs:
- This control: `--curriculum single_hop`; 88 direct examples and no derived two-hop examples.
- Test candidate: `--curriculum source_two_hop`; 88 direct + 24 source-only two-hop examples, presented first within each declared scope.

Both branches retain exact raw answers, completion attempts, errors, adapter-level contrasts against identical input/disabled adapter, program success, anomalous citations and full resource measurements. Actual number/length of supervised tokens and source visits may differ and must be reported; matched ceilings alone do not establish compute-matched FLOPs. Source-stem improvements are assessed on within-run same-prompt contrasts first. Cross-run model-output differences must be paired by the original eight question identities and checked for reader-profile, source, evidence, prompt and decoder identity before interpreting learning-curriculum effects. Different actual startup/model times are recorded, not hidden.

The controlled tasks are already seen; no fresh source-family independent superiority, 99% semantic citations, production cutover, or model acceptance can follow. Keep `production_accepted=false`. Isolated branch-scoped Actions avoid constant base PR edits cancelling hours-long jobs. No production owners or the original main research branch are modified.
