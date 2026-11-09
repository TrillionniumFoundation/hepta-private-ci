# Qualification status record conventions

`validation.json` is the V1 record for this frozen code candidate. It binds the
actual native results, candidate identity, retained artifacts and maintained
source. Later candidates require their own source binding and validation.

| Field family | Interpretation |
| --- | --- |
| `schema` | Versioned record identity; structural changes require a new version |
| `source` | Exact baseline/candidate/tested/maintained identities; no invented SHA or digest |
| `authored_test_inventory` | Parent cases declared in source, separate from run counts |
| `native_validation.attempts` | Every attempt, including compile failure; exact command, source inventory, outcome and original log digest |
| `native_validation.maintenance` | Separate fix/format/compiler evidence; do not imply behavior reruns |
| `mechanism_contract` | Design contract; these booleans grant no authority and replace no original receipt |
| `qualification` | Independent gates; mechanism PASS cannot automatically change custody, learning, production or RSI |
| `actual_round_actions` | What was actually executed this round, distinct from fixture behavior |
| `storage_assumptions` | Preconditions/non-guarantees that remain after test success |
| `publication` | Observed PR/merge/deployment states; publication is not deployment |

Preserve `NOT_RECORDED`, `RUNNING`, `PASS`, `FAIL` and `INDETERMINATE` distinctly,
or use explicit stage-qualified variants as in this record. A PASS must cite the
executed command, exact source and original successful log. Failed earlier
attempts remain recorded. Unmeasured counts, hashes, times and costs stay null,
not zero or an empty digest.

The 19 new parent cases are included in the 141 full-crate successes. Do not add
them to report 160 tests. Nested child invocations also belong to their parent
cases. Test fixtures with separately named keys do not change independent
custody or real-learning gates from HOLD.

The original attempt logs, source inventories and maintenance/compiler records
are retained in the checksum-bound archives. The tested-to-maintained patch
preserves the source distinction. Keep the original failure when adding later
results; a compiler check is not a rerun of behavioral tests.
