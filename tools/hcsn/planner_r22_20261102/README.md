# R22 shared probability validation

R22 removes generic `allclose` overhead from three scalar-one, zero-relative-
tolerance mass guards. It preserves the original FP64 reduction order,
inclusive absolute tolerance, finite/negative/shape checks and accepted values.
The full, packed and anchored callers retain R21 typed restore admission.
All four planners and all fitted cores receive the same implementation change.

`PROOF.md`, the two source diffs and `INDEPENDENT_SOURCE_REVIEW.md` explain the
bounded equivalence. `SOURCE_MANIFEST.json` binds 61 exact local inputs to the
remote source checkpoint recorded in `PUBLICATION.json`. The initial manifest
prepared while the reviewer finalized two files is preserved unchanged as
`PREPUBLICATION_FREEZE_RACE.json`; `FREEZE_PREPARATION_RECORD.json` records that
this was caught before publication or any registered execution.

The profiled hotspot and first fixed-fixture development trial are retained in
`profile_01` and `development_01`. They are development evidence. The registered
independent checker tests actual mass/restore callers, alias and readonly
behavior, inherited refusal paths, unchanged executor/I/O functions, and the
installed NumPy predicates. Its result does not assert a performance gain.

The fixed fresh comparison uses all eight original fitted checkpoints, three
cores, both representations and all four planners. Old/new execute the same
32 worlds per fit, with randomized paired order and independent, charged
caches. `PROTOCOL.json` defines the 48 original adoption groups separately from
the additional 192 software groups. Every declared group is retained; a pooled
average cannot override a failed gate. Complete six-query actor latency and
throughput include real storage work. Traced Python allocations and combined
process RSS have different scopes and are reported separately.

Every episode retains six real file fsyncs and six directory fsyncs, atomic
rename, checksum verification, two readbacks and memory restore. The separate
`cold_confirmation_01` records 117 processes, 54 lost-reply SIGKILL query cuts,
three memory schemas and three policies, including paid WAIT/READ/REFRESH
history. This is trusted local Linux query-boundary recovery; external actions
suspended inside a query, power failure and concurrent ownership remain outside
this contract.

Use `REPORT.md`, `ACCEPTANCE.json` and `COST_LEDGER.json` for final outcomes and
cost scope. All known earlier investment remains charged. Unknown bookkeeping,
supervisor and production costs are null, not zero. No actual 1,000-use reuse
campaign, analytic-only contribution, GPU, energy or production qualification
is inferred from this experiment.

To reproduce registered measurements after restoring the bound dependencies:

```sh
taskset -c 8 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m tools.hcsn.planner_r22_20261102.campaign --output FRESH_OUTPUT
taskset -c 7 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m tools.hcsn.planner_r22_20261102.cold_checks --output FRESH_COLD_OUTPUT
python -m tools.hcsn.planner_r22_20261102.raw_audit --output FRESH_OUTPUT
```

The drivers refuse an existing output folder and verify the frozen inputs and
publication receipt. Measurements require compatible Linux CPU affinity; no
dedicated-host claim is made for the shared project environment.
