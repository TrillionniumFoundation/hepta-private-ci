# R20 test accounting and errors retained

- 20 new mathematical/finite-difference/PyTorch AD/interval/coverage tests: `evidence/TEST_MATH.log`, all passed, zero skipped.
- 25 unchanged R18 math tests: `evidence/LEGACY_R18.log`, all passed.
- 18 unchanged R19 math tests: `evidence/LEGACY_nonquotient_bnb.log`, all passed.
- 6 distinct true-file adversarial tests, run under `python -O`: tests 01-03 in `evidence/TAMPER.log` and tests 04-06 in `evidence/TAMPER_TAIL.log`, all passed. The first multi-test driver timed out while executing test 04, so tests 04-06 were run separately and the interrupted log is retained, not claimed as a complete six-test invocation.
- An initial unittest command incorrectly passed `-s/-p` to the wrong subcommand and started no tests; it was corrected. Neither mishap started efficacy training.
- Every one of the 80 fits is sealed; independent audit verifies all 80 and 4,556 checkpoints with max saved-cost replay discrepancy 0.0. The two rational global proofs are independently re-executed and their frontier SHA256 hashes compared.
- 69 distinct tests overall, zero remaining failures or skips; no reuse of repeated runs in the count. Hosted CI remains separate and unverified until observed at exact PR HEAD.
