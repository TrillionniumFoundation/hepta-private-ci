# CI selection audit of fixed runtime R

This continuation inspects commit `fc0c6f7430cc1cce9274d407536e7249f2290ccd`,
tree `8403d5acabc83707e9b5fcb4e5250a4883c12293`, with parent
`d7c32f38ae1c3890e73ff48ef8ee725ba4e80c58`.

## Actual execution

The unchanged `ci-validate-selection.py` (SHA-256
`85dda7f92d774db9ea0a5709b3bcfda6a50e8dfd396d9a6bc9353a2689bd470c`)
executed the workflow's actual inline audit using 154 synthetic fixtures.
Attempt 2 exited 0 and all 154 outcomes matched expectation: one complete
37-test fixture accepted, 111 individual missing/ignored/duplicate cases
rejected, 40 per-group record/log failure cases rejected, and two obsolete
selection cases rejected. The exact 37 Rust test definitions, selectors,
minimum counts, budgets and original 24 controls were checked again on R.
The workflow Git blob is `392ad92cfdf63c6a1a8281683ec1074a845cff68`.

`ci-selection-audit-r-fc0c6f74-attempt2.json` is the unmodified validator output.
Its accompanying provenance records R's commit/tree, the exact command,
start/end timestamps, exit code, log hash, and matching before/after hashes
for the workflow, nextest wrapper and ten Rust test source files. Both
before/after Git status observations were clean. This audit did not edit the
repository, index or source, and did not launch Rust or inspect hosted jobs.

Native tests executed **by this audit**: **0**.
`audit_did_not_trigger_ci`: **true**.
The legacy validator's `ci_triggered: false` field describes this audit
invocation only. Root separately pushed R to the existing PR; GitHub events
from that push are outside this audit's scope. The field must not be read as
claiming that no CI event occurred during the entire session.

## Preserved first attempt and history

`ci-selection-audit-r-fc0c6f74-provenance.json` and its log preserve the first
invocation's exit 1. The exact tracked workflow was not yet materialized in
the sparse checkout, so its initial read raised `FileNotFoundError` before
any audit fixtures executed. No raw selection receipt was produced. The source
owner then materialized that exact tracked workflow; attempt 2 is a separate
record, with a new output path. The original failure was not overwritten.

The earlier `ci-selection-audit.json`, `ci-scope.md`, baseline workflow and
validator retain their original bytes and f040 attribution. R includes a new
provider observation migration and the four-domain recovery file boundary;
this source audit does not transfer any earlier native result onto R.

## Reproduce

From a checkout of R with these evidence files installed, using Python 3 and
PyYAML, choose an output path that does not yet exist:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 evidence/pq-recovery-owner-20261105/ci-validate-selection.py \
  --repository "$PWD" \
  --output /tmp/hepta-pq-recovery-R-new.json
```

All audit inputs must be materialized. The output is a source/synthetic-log
receipt; the 37 native controls and existing linter still require their own
execution records. Qualification remains `HOLD_NO_GO` for this receipt.
