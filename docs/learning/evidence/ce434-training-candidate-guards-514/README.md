# Training and Candidate guard correction: fixed 514 source

This directory retains the complete original scoped Python results for the
formatting-only guard correction. It does not record a Rust or native pass.

## Source identity

- Baseline commit: `514fe5f53cfdc254477667f8862d652ea756c807`.
- Baseline tree: `490dcafbd5a7f12a8fac19f5fa5b00b5c3ce4879`.
- Corrected commit: `4ae6c73ea7731e69c6819c1d188f8ff26ba1fbb7`.
- Corrected tree: `f2c7d861717117c9d74591db38bbcf19f06f55fe`.
- The corrected commit has exactly the baseline as its sole parent.

The corrected tests ran against the baseline checkout with two staged files.
Their complete Git tree was then published on the separate corrected branch.
Both published blobs were fetched and compared byte for byte with the tested
files; the resulting GitHub tree equals the tested index tree. This evidence
does not relabel the execution as a fresh run at the published commit HEAD.

## Retained results

The baseline ran 56 test methods and reported 72 errors, including subtests.
The corrected run passed the same 56 methods with zero failures, errors or
skips. All 31 owned protected-file rows also passed the existing verifier.
Python compilation of the changed QA file and the staged diff check against
the full baseline passed. No full caller proof, full source suite or Rust
test was run by this qualification.

The only corrected source paths are `CALLERS.toml` and
`qa/b4-no-bypass/test_original_candidate_stage_source_closure.py`.
`complete-row-delta.json` preserves every changed complete row, its original
index, and all 42 marker-slot replacements. The five changed QA strings still
exercise their original mutation controls. No Rust code, scanner, boundary,
inventory, forbidden rule or function-order constraint was removed or changed.

`baseline.log`, `baseline.json`, `corrected-final.log`, `corrected-final.json`
and `handoff.json` are unchanged copies of the original retained artifacts.
`manifest.json` records file sizes and SHA-256 digests for this package.

## Reproduction runner

`qualification_runner.py` was packaged after the recorded runs. It reproduces
the same scoped checks on clean fixed source checkouts and writes new output
outside the checkout. Its presence is not a claim that it has been executed
again. The raw retained logs, rather than a reconstructed console transcript,
remain the evidence for the original outcomes.

```sh
python3 qualification_runner.py /path/to/exact-514 /path/to/new-baseline-output --mode baseline
python3 qualification_runner.py /path/to/exact-4ae /path/to/new-corrected-output --mode corrected
```

The expected baseline exit is nonzero. The reproduction refuses an unexpected
commit, tree, dirty source, changed source during the run, or unrelated manifest
changes. It retains the original negative controls and uses the original
repository verifier without modification.
