# Read-policy task effects without waiting for a knowledge write

This opt-in extension uses the existing event reader, fixed event corpus and
small policy. It does not introduce another model reader or authority path.
Inherited source: de86443df48b633e4694ac94e2fd688fbfc24fd8. Older source-written
knowledge and seven-arm runs remain valid separate experiments; do not cancel
or relabel them. A policy-only experiment need not retrain a three-billion-
parameter reader before observing whether ten learned weights improve retrieval.

## Exact intervention

Before any task-plan argument is opened, train the existing ten-weight policy
on the eight previously declared calibration scopes. Save its source lineage,
reader identity and externally pinned JSON. The subsequent reader command
accepts the policy and its expected SHA-256. Validation rejects changed sources,
withdrawals or overlapping test scope/root before any model call.

The existing six frozen controls are retained byte-for-byte: empty, calibrated
hybrid, entity/revision, deterministic organization, program-bound support and
one omitted prerequisite. Add initial-policy and learned-policy selections on
the SAME initial candidate pool, with the SAME feature function. The program
support/omission controls are authored diagnostic dependencies, not human review.
All eight conditions invoke the same fixed Qwen research reader and deterministic
2,048-input/64-output protocol. No reader optimizer, knowledge adapter or new
answer-generation rule is added. No citations are inserted after inference.

The original eight controlled tasks remain: new fact, explicit correction,
relation composition and constrained program selection. They are already exposed
public development controls, not new independent histories or future windows.
Actual procedure outputs are checked by the same bounded worker in every arm.
The complete 64-answer journal is synced before final task-label parsing.

## Learning, organization and coverage are separate claims

Report the learned policy against initial weights, calibrated hybrid and the
best predeclared deterministic organization control separately. A gain only
against the initialization is not a gain against strong retrieval. Preserve
per-kind strict outcomes and transitions in selection, answer and source coverage.
Extra support coverage without improved final success is counted explicitly.
Failures remain in all denominators and prevent a positive complete-pair screen.
None of these small, authored-template comparisons establishes significance or
independent semantic citation precision.

Keep measured policy write/projection/train work, actual model tokens/seconds,
procedure verification, and original extraction/index receipts. The illustrative
N=1/10/100/1000 write-cost amortization divides ONLY measured policy write time;
it is not total lifecycle cost, a benchmark speedup or an assumed query workload.
Original corpus storage is still retained. Production maintenance, retention and
cross-host recovery costs remain unknown. Total lifecycle cost therefore stays
null and no crossover/production break-even is asserted.

## Execution

```sh
python scripts/memory_cell/experience_policy.py SOURCES.json SCOPES.json POLICY.json --source-sha SOURCE_SHA --scopes-sha SCOPES_SHA --reader-identity READER_ID
HEPTA_MEMORY_TESTED_COMMIT=SOURCE_SHA python scripts/memory_cell/event_reader_experiment.py PLAN INPUTS MODEL OUTPUT --plan-sha PLAN_SHA --stage-sha STAGE_SHA --policy POLICY.json --policy-sha POLICY_SHA
```

No policy argument preserves the existing six-condition experiment. The readonly
hepta-memory-policy-task workflow checks formatting and the full regression suite,
locks the existing corpus/package/model inventories, trains only the small policy
and generates all conditions in a separate process. It has its own concurrency
key so knowledge-writing cannot starve the read-policy measurement. It does not
waive the human-review, qualified-reader or production acceptance requirements.
