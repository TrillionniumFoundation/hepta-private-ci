# Next WSP confirmation stage

This work extends the frozen `wsp_native_value_20261105/value_edit` owner and
retains its source, checkpoint, task, arithmetic and evaluator definitions.
It does not alter the old protocol, original TEST, checkpoint tables or live
Trader. The original five fits remain five fits, with zero new base training.

## Confirmation boundary

`guard.py` binds exact network shapes, F64 tensor bytes, row roles, protected
fields, generators, transition tables and physical time/event semantics.
Its SQLite ledger reserves the complete paired cohort before inference. Every
failed or interrupted attempt consumes the schedule. A changed candidate,
historical schedule, second scoring attempt or repeated run is rejected.
The ledger is a local durable research record; it is not an independent data
authority, a multi-host access boundary or proof that unknown external history
has never seen a sample.

The random control is one signed permutation of the final stored effective
edit. Its L2 and Linf norms must both match after serialization; neither factor
norms nor an unselected solver endpoint define its budget.

Unmeasured Agent tokens, energy, prior search and production recovery costs
remain null/unknown. No financial, energy or production benefit follows from a
finite simulated-task result. Production eligibility also requires retained
capabilities, OOD, calibration, latency and failure measurements.

Run the fault tests from the repository root:

```bash
python3 -m unittest discover -s tools/hcsn/wsp_confirmation_20261107 -p 'test_*.py' -v
```
