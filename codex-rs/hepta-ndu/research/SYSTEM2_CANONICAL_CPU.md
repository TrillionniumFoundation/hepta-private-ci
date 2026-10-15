# Canonical generation: measure actual CPU cost, not only successors

Research-only stacked on PR #1546. The existing `reference` search and opt-in
`canonical_pair` remain unchanged; no production/Reader/Encoder/NDU/Riccati
policy change or new learned head.

## Source and rationale

Canonical pruning suppresses equal-value operand pairs and symmetric duplicates
before emitting a successor. It can increase useful coverage under a
**generated-successor** cap, but the extra value comparisons, hashing and
bookkeeping are not free. Calling fewer emitted successors a CPU speedup or a
strictly resource-matched win would be incorrect.

The preceding fixed generation protocol schedules **1,008** task/budget/profile
records (204 previously exposed plus 48 fixed correlated symbolic tasks, at
256/1,024 successors). This add-on starts only after that protocol has sealed
its original predictions. It rejects missing, duplicate, invalid, incomplete
or drifted source rows, verifies exact proofs and the same generating SHA, and
does not modify the original source file.

## Counterbalanced predeclared CPU measurement

`system2_canonical_cpu.py` runs the same 252 multisets, two budgets and two
profiles for **seven repetitions**, a planned **7,056** timed predictions.
Profile order rotates deterministically with question hash and repeat parity.
Each attempt creates a new heuristic `SearchSession` and calls `advance`.
The timed interval includes session construction, internal state generation and
the session's exact verifier. A separate proof recheck occurs *outside* the
timing window. Record process CPU nanoseconds, elapsed nanoseconds, retained
successors and the original proof/work identity. Abort on proof or work drift.

CPU and elapsed time are not FLOPs, benchmark samples are correlated, results
depend on interpreter/CPU/load, and a matched successor cap does **not** imply
matched calculation. Seven timing repetitions do not create additional
independent tasks, and the previously explored 204:252 task slice is not now
represented as an untouched domain.

The frozen promotion rule is at least **5% CPU median saving at both budgets**
of the 48-task slice, five or more positive paired rounds of seven at each
budget, and no original proof losses in any recorded cohort. Passing would
only justify independent cost confirmation, not production promotion.

## Observed local development evidence (not hosted)

Using exact Git blobs of `SearchSession` and `canonical_successors`:
- `system2_resumable_search.py`: `e6ab44b8385eabe0ae5ff007f3728006b2eef901`
- `system2_canonical_generation.py`: `4ae9cc4fbfd59425b33c3998511caa2fc2da770a`

A local full 1,008-record source-slice replay on 252 fixed multisets succeeded.
On the previously exposed 204 at budget 256, canonical solved 124 vs 122;
on the 48-task slice, 26 vs 24. At 1,024 both methods had the same proof
count (171/204 and 34/48). There were no observed original-proof losses.
Cumulative emitted successors decreased, but this is not equal compute.

The seven-repeat local cost replay completed **7,056/7,056** calls with exact
proof and work consistency. The local Python 3.13 / CPU PyTorch 2.10
environment showed canonical process CPU **slower** in the median:
- prior 204 / cap 256: approximately 7.18% slower
- prior 204 / cap 1,024: approximately 6.28% slower
- new 48 / cap 256: approximately 8.75% slower
- new 48 / cap 1,024: approximately 6.32% slower

Five local unit tests passed; the generated local audit source is *not* an
authenticated GitHub Actions result or independent confirmation. Repeated
timing changes with system load. An attempted unique-value fast-path also
failed to produce a robust speedup and has NOT been added to the runtime.
The current observed verdict is **`stop_no_consistent_cpu_gain`**.

## Hosted run and boundaries

The research workflow retains ALL existing MemoryCell regressions and lint,
the previous budget/stop study, 384 resume comparisons, the frontier-value
study, and the original 1,008 canonical trial. After its prediction seal, it
runs this seven-repeat CPU audit, retains all outputs and source hashes, and
fails closed on incomplete or drifted trials. No old CI guard is waived.

The previous canonical hosted job was blocked by an unused test import; that
single F401 issue was fixed before this added audit. A pushed workflow or a
queued job is **not** a completed pass. The local results above cannot
establish that canonical pruning is faster, and cannot establish NDU/FBSDE
reasoning gains, language/multimodal correctness, or independent evidence
quality. No deployment gate is changed.

Reproduce from an exact checkout after the original canonical run:
```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_canonical_cpu.py \
  /path/to/sealed-canonical /new/canonical-cpu
```
