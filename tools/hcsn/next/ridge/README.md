# HCSN v4 ridge-memory experiment

**Completed:** 4 development runs, 105 frozen confirmation runs, 140 fixed-checkpoint
challenge evaluations, 105 test32 replays, and 350 separate-agent long-sequence
and challenge replays. All frozen implementation/protocol hashes remain unchanged.

**Decision:** the associative-retrieval target was met. The combined FullHX
memory/retrieval acceptance gate was not met: memory seed 2 at length 128 scored
93.84765625%, below the predeclared per-seed 95% requirement. Memory length 512
also remains unreliable. These findings do not authorize the proposed scale-up
under the original condition that preceding results must hold.

## Read first

- [REPORT.md](REPORT.md): complete measured results, seed variation, controls,
  resources, retained failures and interpretation.
- [DESIGN.md](DESIGN.md): API, recurrence, bounded-state/SPD proofs, gradients and
  limitations of normalized ridge memory.
- [INDEPENDENT_AUDIT.md](INDEPENDENT_AUDIT.md): separate-agent review and replay.
- [summary.json](summary.json): machine-readable acceptance and paired effects.

## Principal findings

FullHX, toy HCSN, sigmoid and memory-only ridge variants all scored 100% on
four-association retrieval at lengths 32/64/128 across five seeds. FullHX also
scored 99.961% on eight associations at length 128, 97.500% with noisy filler,
and 99.453% on eight associations at length 512. Toy/sigmoid achieved essentially
the same retrieval results, locating the main benefit in the ridge memory.

FullHX memory at length 128 averaged 98.770%, with the 93.848% worst-seed failure
above; at length 512 it averaged 63.359% with seed SD 37.883 percentage points.
The fixed normalized ridge trades uniformly bounded matrix conditioning for
possible dilution of old sparse information as write mass grows.

On irregular length 128, FullHX averaged 81.660%, versus sigmoid 80.801% and GRU
84.766%. FullHX-minus-sigmoid was +0.859 percentage points with an unadjusted
five-seed nominal 95% interval [+0.022,+1.697]. This finite positive signal changes
both Call and risk shapes and does not isolate a financial Put contribution.

## Integrity and numerical qualification

The core has K=16 and fixed ridge 0.01, with key norm at most one and bounded
values. The exact-arithmetic Gram condition number is at most 101; joint-moment
structure further bounds each read coordinate by five. Ordinary JAX BPTT trains
the discrete implemented network. State/gradient validation passed in FP32 and
FP64, and all replayed accuracy values agree exactly.

Two FP32 solve finite-difference checks at step 2e-5 failed their original 0.003
tolerance. They remain failed in `stress_solve_results.json`. Independent
float64 closed-form adjoints agree with FP32 autodiff within 2.536e-6, and a full
step-size sweep supports finite-difference cancellation. The records distinguish
these observations rather than replacing the original criterion.

`results.json` retains a resource-label error: `fixed_operator_bytes=262256`
counts source float64 arrays. Actual fixed FP32 table storage is 131128 bytes.
[resource_accounting.json](resource_accounting.json) records both quantities and
the correction. The frozen runner and raw results were not overwritten.

## Sources and evidence

`models.py` is the v4 implementation. `protocol.json`, `challenge_protocol.json`
and `freeze.json` preceded all confirmation test construction. `run.py` produced
the 105 checkpoints in `checkpoints/`; `challenge.py` evaluated those same
validation-selected checkpoints without training or reselection. `audit.py`
replayed test32; `independent_audit.py` separately replayed test64/test128 and all
challenges using independently written metric calculations.

The raw evidence is `development_results.json`, `validation.json`,
`results.json`, `challenge_results.json`, `audit_results.json`,
`independent_audit.json` and `stress_solve_results.json`. The initial development
JAX lazy-table tracer error, its original code, and its log remain in
`development_failures/aot_lazy_table/`.

The archived environment used JAX/JAXlib 0.4.38, NumPy 2.3.5, single-threaded BLAS,
and CPU affinity 6–8 for confirmation. Replay commands are `python -B audit.py`
and `python -B independent_audit.py --phase replay`, run from this directory with
the archived dependencies available. `run.py` intentionally refuses to overwrite
a completed matrix. Reproduction should use a separate working copy to preserve
this evidence.
