# Interrupted local-scope receipt inventory

A standard-library, read-only companion to `../local-accounting-batch`. It makes
partial evidence useful after a controller/session loss without turning missing
processes, checkpoints, or an incomplete outer wait into completion. No accounting
formulas, category ceilings, scientific outputs, or dispatch paths are changed.

## API and result

```python
report = inventory.inspect_scope(original_scope_ref, original_source_sha256)
```

Inputs are the original pinned `BOUNDED-LOCAL-SCOPE-v1` reference and source digest.
The inspector checks existing OWNER, CLAIM, BOUND_PROCESS, RAW_WAIT and SETTLEMENT
metadata, including exact scope/config/source/parent/child birth joins and terminal
wait status. Complete nonzero waits remain paid. An absent/invalid settlement does
not erase a consistent raw wait. Repeated process identities are excluded rather
than counted twice. Missing or malformed claims remain explicit unknowns.

`reported_child_cpu_sum` is only the sum of the consistency-checked, distinct child
receipts in that observation. It is **not parent-inclusive CPU, authenticated kernel
evidence, or a complete campaign cost**. A zero sum with unknown records is not free
work. A changed/unreadable snapshot withholds the aggregate entirely. The same
pinned accounting `support.py` validates JSON, bounded regular files and CPU numbers;
there is no cross-call cache or alternate budget formula.

The read allowlist is intentionally narrow. The inspector does not follow source,
config, result, artifact, model or checkpoint references. Those references are only
compared as metadata. It neither authenticates a maliciously rewritten local store
nor verifies payload custody/numerical continuation. Even `SETTLED_METADATA_ONLY`
is **not a claim that a checkpoint is safe to restore**. This is a paid-receipt
inventory, not a numerical-prefix validator or a replacement execution ledger.

Every report keeps:

- current liveness `UNKNOWN`;
- parent-inclusive cost `null`, whole scope incomplete;
- payload custody unverified;
- automatic resume/replay permission `false`, possible unobserved tail `true`.

A separately authorized fresh attempt is not prohibited by this report, but must
retain historical unknown cost/effects, use its own explicit admission and genuine
resource coordination, and never silently overwrite/reuse old claims. There is no
resume, lock-stealing, new process, network call or write API here. No production
registry, survival guarantee, recovery of lost CPU, or scientific execution is
provided. Existing original claims must stay in place.

## Bounded observation

Linux/POSIX Python 3.12+, matching the original local supervisor metadata. Maximum
4096 declared segments, 1 MiB per metadata file and 32 MiB distinct metadata bytes;
readback revalidation may read those same bytes once more. CPU numbers are limited
to 128 coefficient digits and exponents from -128 through 128, then summed by exact
integer scaling independent of ambient Decimal precision. Only allowlisted paths
are opened. JSON duplicate keys, booleans as IDs/costs, negative/nonfinite costs,
symlinks, unexpected claim/orphan directories and changed reads fail closed.

Directory and byte rechecks detect observed changes, not an atomic filesystem
snapshot. A writer may append immediately afterward; the inventory therefore never
claims the observed frontier is globally final or that the old owner is dead.
No `wait4` observation is reconstructed from files or from current PID absence.

## Qualification and publication boundary

```sh
python3 -I -B -W error qualification/joint-generation/local-recovery-inventory/test_inventory.py
```

The suite uses handmade JSON, fake process IDs and fake reported CPU amounts only.
It never loads real experiment data, models, result JSON or checkpoints. Test counts
are actual executed unittest cases; negative mutation subcases are not counted as
separate test cases. The qualification wrapper pins all source hashes before the
single test process and records its actual complete `wait4` cost separately from
these fake receipt values. No nested numerical workers are started.

The original `/workspace/shared/ndu-migration-20261024/benchmark.lock` directory was
absent in this executor snapshot. Qualification uses its own **synthetic-only**
lock and does not recreate or pretend to own the missing historical shared lock.
That lock cannot authorize a scientific rerun. Supervisor/authoring and final
observer tails remain additional unmeasured cost, not zero.
