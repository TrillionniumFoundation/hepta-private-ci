# Surviving local HCSN engineering evidence — 2026-11-06

These files survived the local execution-environment interruption on disk. Recovery only read existing files and immutable Git source objects. No test, training, build, worker or CUDA campaign was rerun, and no implementation source was changed.

## Retained stages

- `python-tests-01.log` reports **56 tests, OK**. Its associated freeze lists 49 Python files. Compared with recovered source snapshot `e989d51b0da0617aa20a1fccbcbcb4ad01571ff4`, 47 still match. Two verification wrappers changed after that suite: `verify_host.py` received the failure-reporting guard, and `verify_supervised_worker.py` stopped compiling an unused fixture on the signed-worker path. The exact old/new hashes are in `manifest.json`. This is evidence for the frozen stage, not a full-suite result for the later wrappers or the final Git head. No separate original SHA receipt for the Python log was recovered; its preserved bytes now have an explicit recovery hash.
- `native-tests.log` reports **195 passed, one skipped helper**. Its SHA256 exactly matches the original `native-tests-source.json` receipt. The three pinned native source/lockfile hashes also exactly match the recovered source snapshot. This stage covers neuron and learning-owner tests before final formatting; it does not establish full Agentd runtime qualification.
- `automation-tests.log` records a **linker Bus error and command exit 101**. It is retained as a failed attempt and must not be counted as a passed automation suite.
- The independent numerical logs retain the initial fixed-spatial-grid time-refinement freezing diagnostic, its CTMC replacement diagnostic, fixed-generator and spatial-error checks, parameter finite differences, and resumed-block gradient checks. The generator test's first overly strict semigroup assertion failed; the failed log remains beside the subsequent five-test pass. Baseline A/B resumed-derivative tests and the later age-backend case are separate historical executions.

The five source hashes recorded in `independent-hcsn-gap-review.json` all match the recovered snapshot. That JSON is an in-progress review from its original timestamp, not a newly executed acceptance or a replacement for later gates. Fixed-generator time consistency and a zero-drift spatial oracle do not establish convergence of the full nonlinear renewal model. Gradient connection and finite differences do not establish learning benefit.

## Raw evidence that was not recovered

The complete new local bridge directories for **A a-05, B b-04 and population_age age-04**, including their second-block outputs and original combined acceptance summary file, were in the lost RAM task directory and were not recovered. Earlier tool observations and summary/result hashes remain, but this directory does not reconstruct or impersonate those raw outputs. Existing older bridge evidence in the repository base is not a substitute. Final CI must rebuild the exact final source and execute all three combined bridges and second-block recovery again.

The current disk Cargo stream and old strip receipt are deliberately excluded: the former differs from the final deployed build stream and the latter describes the old `5f09b890...` binary. The final `2a195957...` native build linkage, Cargo stream and strip receipt were independently preserved with the actual ai395 outputs in sibling physical evidence commit `a30850dd226c625f175ed50c1660bb09f1b77b8a`.

## Boundaries

This retention does not change production registration, production trust or adoption status. It does not claim a scientific result or a new CUDA run. The physical ai395 helper validated one block with exact complete-state replay; that remains distinct from the lost local second-block raw evidence.

`manifest.json` binds every retained original file by size and SHA256 and records the source comparisons and limitations. The companion scratch archive is deterministic: sorted regular-file entries, fixed metadata, and XZ compression.
