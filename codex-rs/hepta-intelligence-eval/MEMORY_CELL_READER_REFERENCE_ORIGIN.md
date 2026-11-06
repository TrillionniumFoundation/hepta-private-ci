# Reader reference originating-run qualification (2026-10-14)

## Why the historical reference receipt must remain blocked

An earlier generation workflow
[38046364381](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38046364381)
was pinned to generating commit
`1879c0c52748e29739a12e4d4217a17dd7ac24c6` on PR #1452.
That workflow's **final conclusion is failure**, not successful multi-model
verification:

- The `qwen-3b` job ran model inference but then failed during
  post-processing: the old `reader_reference.py` incorrectly called
  the dict-only `tensor_contract.strict_json` on an array of scored
  answers, raising `ValueError: candidate object required`.
- The `smol-1.7b` job was cancelled and did not establish the complete
  original eight-condition outcome.
- Both jobs retained some GitHub artifacts. Their ZIP presence alone does
  **not** certify full, successful Reader completion.

The newer `reader_reference.py` uses the dedicated array-aware
`strict_records` instead. **That source fix cannot retroactively
relabel a failed historical model execution as successful.** A new
completed source-pinned model run must be verified before any official
new reader-reference receipt can replace the historical run's role.

## New fail-closed run admission

`scripts/memory_cell/reader_reference_run_gate.py` checks the immutable
generating workflow ID, full source SHA, first run attempt, run status and
conclusion, complete model-artifact metadata, original input ID/SHA-256 and
exact artifact name/SHA-256 identities. If any component is unavailable,
failed, cancelled, expired, mismatched or incomplete, it writes a
machine-readable `model-run-admission.json` identifying why no replay is
qualified **before terminating with a failing status**. It cannot issue
download pins for a failed run.

`.github/workflows/hepta-memory-reader-reference-receipt.yml` now invokes
this parser, runs its fail-closed unit tests and retains the original
GitHub metadata, source files, failure logs and SHA-256 manifest. The
original replay and original completion gate remain enforced: no skip,
success override or substitution of simulated answers.

A *separate*, read-only workflow
`.github/workflows/hepta-memory-reader-reference-run-gate.yml` tests that
the known historical **failure** is correctly classified as ineligible.
A successful negative-control audit verifies honesty of accounting; it
does not prove either frozen Reader model works on the complete benchmark.

## Remaining independent acceptance

A future fully successful, byte-pinned two-tier model run is still required
before any legitimate fresh replay, followed by exact raw answer, evidence
delivery, token-budget, actual Reader time/cost and reference comparison
checks. Published labels, model-assisted sufficiency claims and authored
corpora do not replace independently reviewed citation entailment or
prospective task evidence.

**Qualification status:** unavailable for the failed historical run.
`production_accepted=false`, `semantic_citation_precision=null`.
No branch protection or `blocking-ci` rule may be waived.
