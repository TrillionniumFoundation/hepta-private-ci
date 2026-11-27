# Requalify the reviewed VERIFY head after CI-only changes

At e789acfb06714c02b9c99b761e79975c8cd48ea6, Architecture run 42756620302
passed source-head 129632378553, base-merge 129632378589 and required check
129643510835. The prior 61d94bd6 source rerun also passed both lanes and required.
The original quinn transport failure remains preserved, not rewritten as drift.

Blocking run 42756620731 still fails at cargo-deny and multiple Bazel test jobs;
repo-checks, Codespell and three Native Hepta paths succeed. cargo-deny log
129632493154 again returned Transport closed. No advisory cause is inferred.

The VERIFY workflow did not run on script/workflow-only successors because its
path filters excluded them. Broaden its triggers to CI scripts/actions/workflows
and dated VERIFY qualification records, including research/verify2-* push refs.
Keep workflow_dispatch and the original risk-cell push ref.

Checkout, source assertion and artifact name now bind the actual PR head SHA,
falling back to github.sha for non-PR events. This makes the recorded commit
explicit rather than relying on a prospective merge commit. Preserve the three
platforms, full unit discovery, original SQLite effects, dispatch smoke, timeout,
concurrency, always-retained artifacts, read-only permissions and disabled
credential persistence. No native or scientific acceptance criterion is relaxed.

Structural YAML validation checks representative positive/negative trigger paths
and unchanged execution contracts. RESULT.json records that validation; the ZIP
retains the complete original source-head log, original workflow and CI snapshots.
MEMBERS.json binds exact bytes. New-source platform and full CI remain pending.
Independent real-task labels, complete cost and prospective utility stay HOLD.
