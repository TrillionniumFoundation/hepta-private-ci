# Frozen readout proposal: one physical realization

The V7 analytic proposal now has a separately admitted physical check on the exact original parent and two retained engineering observations. The new complete in-memory state is `ff40bb39b480ccb021e0d51a7d7b4a22a26a6a8d920db88555aca1b9ef7b197f`; it was not exported or adopted.

One model load and one four-tick, two-row forward completed. Exactly two declared readout elements changed. Maximum endpoint absolute error was `2.842170943040401e-14`, within the prospectively frozen `1e-9`; feature-zero error was `0`, within `1e-12`. All physical, source, input and state invariants passed, and the parent state `136026bd...` was restored in memory.

`PROTOCOL.json` remains an inactive template; the distinct `ROOT_ADMISSION.json` fixed its source, budget and tolerances before execution. `SCOPE_REVIEW.json` is the earlier static review, not execution authority. The original claim, LOAD/EDIT/FORWARD attempt receipts, RESULT and complete H receipt preserve the single execution. The interpreter-metadata preflight had an unresolved launch; runtime acceptance comes from the completed physical loader check.

`ARCHIVED_INPUT.json` remains the old candidate's unchanged data source. Only its input and initial-state payload was reused with a fresh input identity. The request is in `../actual_inverse_v7/READOUT_REQUEST.json`; the proposal is in `../actual_inverse_v7_results/READOUT_PROPOSAL.json`. Original checkpoint/profile/source pins and exact interpreter paths remain required.

No original gate was replayed; there was no parent forward, derivative, new parameter solve, optimizer, export or retry. The physical model's own QVI, matrix exponential and discounted linear solves remain part of its forward. This result does not establish new-task generalization, cold adoption, retention, real A-to-B learning, full-field recovery or a training advantage.
