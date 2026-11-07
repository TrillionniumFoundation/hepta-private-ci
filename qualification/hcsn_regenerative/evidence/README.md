# Preserved reference and campaign evidence

The latest source-bound local receipts are:

- `final-combined-tests-v2.json` and `final-combined-tests-v2.log`: current
  68/68 unit/integration methods across the new reference, independent oracles,
  causal reader, complete ledger and event adapter. The earlier 67-method
  `final-combined-tests.json` and `.log` are retained separately.
- `audit_final_v4.json` and `audit-final-v4.log`: 91 explicitly scoped numeric
  checks. `user_decisive_requirement_complete` remains false.
- `source_separation.json`: byte identities against the candidate parent and
  original campaign, including their inherited baseline difference.
- `source-publication.json`: source-file and local/remote Git-tree binding,
  added at publication time; it does not manufacture an execution receipt.

Historical attempts are append-only. `audit_preflight_raw.json`,
`audit_preflight_refinement.json`, `audit_initial_full.json`, `audit_final.json`,
`audit_final_provenance.json`, `audit_final_v2.json` and `audit_final_v3.json`
retain prior source states and refinement decisions. Later receipts supersede
their qualification scope but do not erase failures or change their source
hashes. A source file's final hash must match the latest receipt, rather than
being inferred from an older passing count.

Review artifacts preserve concrete counterexamples and fixes:

- `generator-test-attempts.json`: initial generator test attempts, including
  the failed infinite-edge case and subsequent checks.
- `process-nonfinite-before-fix.json` / `process-nonfinite-after-fix.json`:
  finite extreme parameters and rewards producing unresolved FP64 results,
  then explicit rejection and targeted regression tests.
- `ledger-and-stream-review-checks.json` / `ledger-and-stream-PARENT_REVIEW.txt`:
  interrupted partial-state replay and omission of a failed attempt's cost.
- `root-review-before-repair.json`: nonfinite factorial statistics and an
  event inserted behind an already queried time frontier. Final tests include
  their repairs; the original observations remain unchanged.
- `ready-time-review-before-repair.json`: a lazy callback result was not
  materialized until time 900 but was marked ready at 100 and affected a query
  at 100. The final adapter samples readiness after the immutable CPU token
  snapshot is complete; a new regression reproduces this ordering.

`desktop-original-20261107/` is a read-only observation of the continuing
original campaign, not a newly launched run. Its `publication-allowlist.json`
lists the 42 selected raw evidence files and their hashes. Only those files
and the manifest were copied from the acquisition workspace. Its complete
reconciliation, raw directory coverage, terminal files, checkpoint hash
readbacks, original OOM, rematerialized probes, parity results and B audit
protocol are retained. Observations are explicitly non-atomic because the
owner was still running.

The campaign's 52,131.828957 seconds of inner completed train/validation time
is contained in its 57,049.943661 seconds of outer completed-attempt time;
these must not be added. The pre-full stage receipt has an outer elapsed
829.063943 seconds, with individual probe timings nested inside it. The
current open attempt's eventual cost is not yet measured. Physical energy
remains null wherever measurement failed or was unsupported.

Full goal status, numerical limitations and next dependencies are in
[STATUS.md](../STATUS.md). The code and evidence do not claim that a new
trained model, real streaming encoder, or scaling/deployment gain exists.
