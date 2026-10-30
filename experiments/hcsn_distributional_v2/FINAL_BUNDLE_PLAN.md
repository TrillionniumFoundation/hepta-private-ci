# Final three evidence bundles

This plan assigns paths, not outcomes. The final include lists are generated
only after the relevant writers have exited and their completion proofs are
stable. The main checkpoint watcher continues separately; its complete run
bundles remain unchanged.

## 1. `lif_supplement001_evidence`

Include the complete immutable LIF campaign, source snapshots, analysis,
normalization, and its independent outer measurement:

- `results/lif_supplement001/`
- `results/lif_analysis001/`
- `results/lif_cost_receipts001/`, including actual `BINDINGS.json`
- `results/lif_cost_normalization001/`
- All `results/lif_preflight*`, registration-failure evidence, and other
  top-level `results/lif_*` evidence and process logs
- `results/content_lif_review001.json`
- Canonical `LIF_SUPPLEMENT001_PROTOCOL.json`, `lif_supplement.py`,
  `lif_supplement_analysis.py`, `lif_cost_receipts.py`, and the bindings template

The adapter's complete-child cost is already inside its measured outer
receipt. Its internal self clock is preserved as nested evidence and is not
charged a second time. The same containment rule applies to training workers,
candidate clocks, analysis body clocks, and the enclosing scheduler tree.

## 2. `content002_metadata`

Include main-study metadata and source, with run directories and worker logs
already covered by `content002_runs_*`:

- `results/content002/` metadata, source snapshots, scheduler/supervisor files,
  final progress/completion, and any other non-worker evidence
- `results/content_analysis002/`
- The independent `results/content_analysis_supplement001/` and its full
  `results/content_analysis_supplement001_execution/` measurement, plus
  `results/content_supplement001/` registration/diff/source evidence
- External analysis stdout `results/content_analysis002.log`, plus the
  analysis request and watcher source files
- The fully terminated `results/content_checkpoint_archives/` evidence:
  outer archive receipts, process logs, publication records, instance records,
  final status/completion and operational review; internal `work/` is excluded
- Canonical `CONTENT002_PROTOCOL.json` and the main content implementation and
  supporting content/checkpoint documentation; canonical
  `CONTENT_SUPPLEMENT001_PROTOCOL.json` and its derived analyzer

The original strict analysis remains 175 valid / 1 invalid. Readiness binds
that exact failed record and the separately registered, explicitly post-hoc
producer-exact supplement with 176 valid / 0 invalid and unchanged statistical
gates. Neither the plan nor the closure calls the original strict gate passed.

The plan refuses to compensate for an unsealed main run by quietly placing
it in this metadata bundle. Every main run file and process log must already
match the completed checkpoint bundles. The final checkpoint watcher self
receipt must exist before its metadata is selected.

## 3. `v2_auxiliary_evidence`

After the first two final bundles are complete, include every remaining
eligible immutable package file not already covered byte-for-byte. This
includes:

- Both canonical `SCALING001_PROTOCOL.json` and `SCALING002_PROTOCOL.json`, the
  original unexecuted `results/scaling001/` identity/block record, and its
  preserved original preflight; the entire actual `results/scaling002/` suite,
  all 30 case receipts and raw outputs, source snapshots, registration, report,
  suite outer measurement, and scaling preflight evidence
- `results/figures001/`, final `results/figures002/`, and independent
  `results/figures002_execution/`; final figure hashes and source identity must
  match their manifest before selection
- Uncovered numerical, control, runtime, content-engineering, failure,
  verification, reproduction, source-snapshot and process-log evidence
- In particular `results/final_report_guard_tests001/` is included: it is an
  engineering test, not the final report output
- The canonical earlier `CONTENT_PROTOCOL.json`, remaining implementation
  files, `measured_support.py`, `RELATED_WORK.md`, and other eligible stable
  package documentation
- The outer receipts/logs of the preceding LIF and main metadata seals

The original and supplemental registrations, plus the earlier aborted-content
protocol, are therefore present in the final member union. None of the three
early bundles contained these canonical root protocol paths.

## Exclusions

The following are excluded explicitly, not by looking at a score or success
value:

- Formal `artifacts/` manifests/parts/closure. These are published separately.
- Every internal `work/` staging subtree. Directory traversal prunes these
  trees before reading files.
- Interpreter caches, coordination lock files and incomplete `.tmp` outputs.
- Files already present with the exact same path, size and SHA-256 in a
  successful formal bundle. A changed file at a covered path is an error.
- Root canonical `README.md`, `final_report.py`, `campaign_costs.py`,
  `CAMPAIGN_COSTS.md`, `archive_closure.py`, and `ARCHIVE_CLOSURE.md`. Root will
  publish these directly in Git. Their already-created test/source snapshots
  remain eligible.
- Actual final cost/report/closure output directories and their enclosing
  execution receipts, including `results/archive_closure001_execution/`.
  Names such as `final_report_guard_tests001`, `campaign_costs_tests*`,
  `campaign_costs_probe*`, and `archive_closure_*tests*` are not excluded by
  this rule.
- `reproduction_receipts/final_catalog001` and its later enclosing records,
  which are produced after sealing and published directly.
- The planner's own `results/final_bundle_plans/` metadata and the auxiliary
  bundle's own sealing state. These remain outside payloads to avoid
  self-reference. The actual archive wrapper inserts its immutable selection
  manifest into each bundle.

Root README/final report/final cost/closure and their own final measurements
are deliberately outside these payloads. No final bundle is rewritten to
include a measurement that was created by sealing or auditing that bundle.

## Commands after root's readiness notification

The planner does not launch a seal. Run it once with a fresh plan directory,
then use the exact include list in one independent wrapper process:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.final_bundle_plan --bundle lif_supplement001_evidence --output experiments/hcsn_distributional_v2/results/final_bundle_plans/lif_supplement001_evidence_001
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.seal_bundle --name lif_supplement001_evidence --include-file experiments/hcsn_distributional_v2/results/final_bundle_plans/lif_supplement001_evidence_001/INCLUDES.json
```

Repeat in order for `content002_metadata` and then `v2_auxiliary_evidence` with
their own fresh plan directories. The auxiliary plan additionally requires
both preceding manifests, all 30 scaling attempts, and completed final figure
rendering. Its residual selection rejects any new unsealed LIF or main-study
file after those bundles, instead of silently moving it into the auxiliary
bundle.

Each `PLAN.json` preserves exact selected files, sizes and hashes, existing
coverage manifest hashes, exclusions, prerequisite hashes, and the seal
command. It also checks the explicit argument list against a conservative
system argument-size budget. Its own CPU-through-receipt is separate from
the subsequent seal process and archive child. Once the wrapper completes,
the formal manifest and all part hashes form the upload manifest; they are
reported to root immediately for publication.
