# Execution05 resource backpressure boundary

## Reconstruction status

This adapter, its tests, and this document were reconstructed from the retained conversation after the workspace disappeared on 2026-10-30. The repository was restored from public commit `6b9353d8fd5ba2d05346afb0772dc49daa6038bd`. The reconstructed files are a new revision: no previous hash or test result certifies these bytes. Fresh source descriptors, execution measurements, and test results are recorded under `validation/resource_backpressure/`.

The adapter addresses explicit admission rejection before a pending persistence operation has begun. It keeps the same live worker, prepared payload, scientific state, and output cursor. It does not restart a worker, replay a gradient or branch, rerun a scorer, catch allocator `MemoryError`, or certify an earlier failed episode as complete. Linux `flock` and cgroup v2 are required. Frozen scientific files remain byte-for-byte unchanged; only registered operational aliases are replaced in a scoped context.

## Installation contract

Construct one `BackpressurePolicy` per process with the registered RAW root, a new private receipt directory outside RAW/CAS, the externally registered source root and source SHA-256 map, the original externally fixed monotonic execution deadline, the original OOM/oom_kill baseline, a mandatory nonmutating health callback, and the registered maximum duration of each pending wait. Polling is positive and at most one second. Production must not pass `test_profile_reader` or `allow_test_policy=True`.

The source map must include every path in `resource_backpressure.REQUIRED_SOURCES`. These pins come from registration. Deriving them from the files currently present is valid only for synthetic test fixtures. Ordinary source-freeze validators and the loaded-source closure remain in force; the new operational files must appear in the complete freeze. The minimum adapter closure includes the original C `architecture_store.py` and R `replay_terminals.py` classes whose persistence boundaries it uses.

```python
policy = BackpressurePolicy(
    root=registered_raw_root,
    journal_directory=unique_private_process_receipts,
    source_root=registered_source_root,
    expected_sources=registered_source_sha256_map,
    deadline_monotonic=original_absolute_deadline,
    oom_baseline=original_oom_baseline,
    health_check=original_nonmutating_health_check,
    max_wait_seconds=registered_capacity_wait_seconds,
)
with installed(policy) as installation:
    previous_budget = controller_core.StorageBudget
    controller_core.StorageBudget = installation["budget_type"]
    try:
        controller_core.run(arguments)
    finally:
        controller_core.StorageBudget = previous_budget
```

Workers, endpoints, analysis parent/child, and finalization each need their own installation around their ordinary entrypoint. Installation in the controller does not propagate Python aliases through `exec`; the registered child launcher must install the adapter in each new process.

The external health callback retains any outer controller/process deadline, ownership, source, and integrity checks required by the entrypoint. It must not perform scientific work, mutate the pending payload, acquire a storage writer lock, or recursively call this storage budget. The adapter adds original A/B/W/R CPU/wall/microstep callbacks, C store limits, cumulative endpoint limits, and the analysis monitor's one-hour/OOM callback. The analysis wrapper starts its hour immediately before entering the unchanged monitor, no later than that monitor's original start, and removes its callback on exit. The controller's outer time anchor must be supplied by integration.

## Eligible wait and unchanged limits

Only `CapacityDenied`, created by this adapter from the original precommit inequality, can wait:

`effective_current + rounded_pending_allocation + 1 GiB margin + current pending worker growth <= cgroup limit`.

The original clean-inactive-file calculation and pending-worker reservations remain. No margin, worker reservation, growth term, or finite cgroup limit is reduced. Each attempt also checks the original physical free reserve (256 MiB), inode threshold (2,000), global logical RAW cap (2 GiB), and applicable C training evidence cap (350 MiB).

A/B/W/R retain 7,200 CPU seconds, 10,800 wall seconds, and respective 39,168 / 23,040 / 2,880 / 32,256 microstep ceilings. C retains 43,200 CPU seconds, 21,600 wall seconds, and 57,536 microsteps. Endpoint accounting retains its original cumulative training-plus-evaluation limits. The two-worker concurrency and 768 MiB registration reservation remain unchanged; the original active-worker rows determine actual pending growth.

At a known boundary, `prepare` captures and rechecks the target inode, size, timestamps, link count, open descriptor cursor, and payload digest where applicable. An explicit memory rejection exits the entire write-lock scope. The same pending operation then waits outside the writer locks with its unchanged wait start, absolute deadline, OOM baseline, and original phase-limit callbacks. Re-entry checks the guard and full resource budget before committing once. A changed target, cursor, or mutable payload fails closed.

Once mutation begins, no exception triggers a retry, including an erroneous `CapacityDenied` raised inside commit. Allocation failure, short writes, fsync failure, journal failure, unknown partial writes, disk/inode/cap exhaustion, source mismatch, target mutation, OOM increase, or time/work exhaustion aborts the operation. A failed text buffer cannot be replayed by later flush or close. If failure-journal persistence also fails, that error is attached to the original exception without masking it.

## Boundary coverage and low-memory evidence

| Boundary | Operational adaptation | Verification |
| --- | --- | --- |
| Controller/analysis StorageBudget write, JSON, append | Retained immutable payload; original pending-replacement semantics; writer lock exits on denial | Independent process obtains actual `.ops-write.lock`; exact appended bytes; foreign target mutation rejected |
| Worker guarded open/write/text/truncate | Admission before mutation; FD/path/payload guard; original bounded failure JSON exemption; failed buffers terminal | Real guarded JSON/text; single serialization/write; short write, allocator failure, postcommit receipt failure cannot replay |
| A/B/W budgets | Original `check_work` remains active during wait | A CPU/wall and B/W physical-gradient gates stop pending operations |
| R budget and terminal persistence | Prepared bytes retained; `R_WRITE.lock` and `.ops-write.lock` exit together | Independent process obtains both actual writer locks; persisted-byte cost added once; R gradient gate retained |
| C EvidenceStore | Original class and CPU/wall/step/cap checks; explicit eligible transaction replaces outer writer-lock wait | Original class loaded from AST without model import; C wall gate; counting checkpoint serializer called once; artifact appended once |
| Endpoint | Original root/registration guarded-write signature; cumulative training and endpoint limit callback | Root API and alias restoration; cumulative endpoint wall limit inside wait |
| Analysis monitor | Original one-hour/OOM checks active while pending stdout waits | Original hour aborts the same monitor invocation; pending log uncommitted; callback removed |
| Literal finalizer | Already-read chunk retains destination cursor/source identity/digest; physical duplicate does not double logical RAW | Actual copy/hash/counts; source unchanged; original success keys; cursor mutation and one-byte allocator failure preserve exact residue |
| Worker admission | Original registered PID, two worker slots, shared phase-lock ownership | Actual own PID registration; slot reusable after exit; zero storage writer depth |
| Failure receipts | Original bounded emergency exemption | <=64 KiB failure JSON succeeds after normal health/RAM failure; oversized exemption rejected |

Worker slot, phase, and controller locks represent ownership/quiescence and remain held where required by the original contract. Both persistence writer locks (`.ops-write.lock` and R's `R_WRITE.lock`) are released for eligible waiting.

The reconstructed suite contains all 33 previously identified behavior classes. It uses synthetic finite cgroup profiles for deterministic fault injection, actual low-memory files, and actual independent-process locks. C and R fixtures execute unchanged class definitions extracted from the restored source AST; the C serializer is a counting byte fixture. Wall-limit tests deterministically advance their fixture's original clock/accounting anchor after the wait begins, avoiding assumptions about millisecond scheduling on the restored host. No test imports Torch/NumPy or executes scientific work.

## Evidence and accounting

Each process gets an exclusive private `CAPACITY_EVENTS.jsonl`, capped at 1 MiB, with each event capped at 64 KiB. Receipt writes check physical reserve/inodes. This declared, bounded operational evidence write is outside RAW/CAS and does not recursively apply the RAM gate it records. Actual allocated bytes and CPU/wall cost still belong in execution-level operational accounting.

Each wait records the first actual rejection, the final rejection, denied-check count, elapsed wait wall time, zero writer-lock depth, and `scientific_work_repeated: false`. Success additionally records the actual accepted admission profile immediately preceding commit. Intermediate rejected profiles are counted but not all persisted. The policy exposes cumulative `wait_count` and `wait_wall_seconds`; original process/owned-child CPU and wall accounting remain authoritative for total cost.

Evidence-budget exhaustion fails closed. No failed attempt becomes successful because a receipt write failed. Repeated rejection does not reset the same pending operation's bounded-wait start, absolute deadline, or OOM baseline.

## Explicit unsupported boundaries

- An unknown outer storage writer lock is never unwound by guessing. A check under that lock may succeed; explicit capacity rejection propagates immediately without sleeping. Fresh execution05 must not use the legacy controller resume-admission mutation path.
- Nested adapter installation is rejected. Arbitrary third-party writers, foreign lock protocols, and uninstalled child entrypoints are not certified.
- Existing source/freezes, integrity checks, complete-loop requirements, ancestry/import checks, and final hashes remain independent mandatory gates. Backpressure does not create a scientific resume cursor or make partial A-29 evidence reusable.
- A persistent real capacity deficit still terminates at the registered wait/deadline gate. Synthetic tests do not establish real production admission, completed science, or recovery of lost local evidence.

## Validation command

```sh
python3 -B -m unittest operational.parameter_field_recovery05.test_resource_backpressure -v
```

Fresh validation JSON and transcript identify the exact reconstructed source hashes, runtime, all test names/results, owned process CPU/wall/RSS, and observed OOM counters. Never relabel an older receipt as validation of changed bytes. A code change after this validation needs a fresh test result and corresponding descriptors before registration.
