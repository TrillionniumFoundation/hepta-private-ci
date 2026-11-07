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

## Ledger finalization follow-up

This change is for a separately frozen future run. The original frozen protocol,
scientific records and failed WAL reopen evidence are not changed or requalified.
The new implementation uses SQLite `journal_mode=DELETE` and `synchronous=EXTRA`
and checks the values returned by SQLite. EXTRA adds a directory sync after the
rollback journal is removed at commit; see the official
[synchronous documentation](https://www.sqlite.org/pragma.html#pragma_synchronous).

`Ledger.close()` requires a quiescent ledger. It checks complete database
integrity and hashes the ordered rows of all three tables, closes the connection,
opens the same database normally with `mode=ro`, and checks integrity and the
complete logical snapshot again. It does not use `immutable=1`, omit a WAL,
reconstruct results or rewrite the database to make validation pass. Successful
worker termination emits `LEDGER_FINALIZATION.json`; a failed finalization raises
and prevents a successful process exit. Existing WAL-format databases, including
closed WAL databases without sidecars, are refused before SQLite opens them.
Their recovery or migration requires a separate, reviewable operation.

The retained real incident has a consistent 2,880-COMPLETE main database and an
inconsistent valid WAL overlay. Its cause remains unknown. The old unmodified
WAL implementation also **passed** a clean synthetic 320-world, nine-arm workload
with 5,760 claim/record commits and a fresh-process reopen. That control does not
naturally reproduce the incident or prove an SQLite or overlayfs defect.

The follow-up suite passes 19 tests: the existing 13 checks plus six process
tests. The additions check all 2,880 synthetic result digests after normal process
exit, SIGKILL after reservation, after claim and after result persistence without
a reply, recovery of spilled uncommitted pages through SQLite's rollback journal,
and refusal of both active and closed legacy WAL inputs without altering them.
See `ledger_finalize_evidence/BASELINE.json`, `FIXED_TESTS.json` and
`RETAINED_WAL_DIAGNOSIS.json` for the measured scope. These are application-crash
and close/reopen checks on the observed environment, not power-loss, general
filesystem durability or original live-WAL recovery qualifications.
