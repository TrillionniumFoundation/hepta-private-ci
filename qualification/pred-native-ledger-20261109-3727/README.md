# PRED frozen snapshot and late readback: stage 2 of 2

Base: `f5f2ca267c7e58b3a14bfc1381bf84d67dd42a15` (#5523).
Scientific qualification remains **HOLD**. This stage supplies no new registered
campaign, independent task evaluation, production owner assembly or training gain.

`scripts/hepta_pred1/native_ledger.py` reads one exact native TaskFlow identity
through SQLite `mode=ro`, `query_only` and a single WAL-aware read transaction.
Attempt, initial observation and reconciliation are retained separately. Fresh
collector monotonic availability and an explicit arrival cursor govern visibility;
native dispatch/receipt timestamps remain raw metadata. A dispatch boundary does
not establish provider acceptance or execution.

`freeze_snapshot(path, encoded_history, collection)` saves existing causal encoder
inputs in a create-only canonical, size-bounded, SHA-checked artifact.
`join_readback(path, snapshot_path, later_collection)` requires the same full
owner/run/step/attempt/intent/payload/binding/destination, clock domain, a later
cursor, and nondecreasing availability. It refuses changes to initially frozen
native facts and writes a separate artifact. Each join checks the initial
snapshot; this API does not chain every intermediate readback automatically.

Raw `OWNER_SETTLEMENT` remains separate from business-effect evidence. Even a
native `succeeded` row supplies no business outcome, duration or physical-cost
label here; the resulting effect supervision mask is wholly unknown. The host
must authenticate database provenance, identities and clocks, retain a clock ID
across same-boot reader recovery, and sequence arrivals with its history encoder.
There is no automatic native-row-to-ActionEvent phase conversion in this stage.

Six new behavior tests use real SQLite/WAL with **synthetic owner rows** and
byte-exact native migrations 0011/0013. They cover the Python 3.10 API fallback, read-only access, missing and
indeterminate records, later reconciliation, identity substitution, same-tick
availability, immutable facts, corruption, overwrite refusal and a fresh Python
reader reopening the frozen numerical snapshot. Reader recovery is not native
owner execution recovery. Validation and exact new source hashes are adjacent.

The historical 189-fit diagnostic is **ORIGINAL_ARTIFACTS_NOT_LOCATED**, not
declared lost. GitHub branch/PR and relevant workflow-artifact searches found no
published campaign; bounded local source/output searches and Mac/ROG top-level
PRED-directory checks found no original. The controller workspace query timed
out. Prior prose saying 189 fits completed in about 30.1 minutes cannot replace
the original COMPLETE result, outer EXITED/0 receipt and checkpoint inventory.
No formal fit outcomes were opened and no campaign was rerun or reconstructed.
The two historical confirmation sets remain sealed.

Next: recover that original evidence and run the already frozen checkpoint
replay; separately collect complete live owner/observer records, bind real
effect labels and units, train the one-step predictor, then register and measure
decision utility against the cheap Fixed1 and matched-cache short horizons.
