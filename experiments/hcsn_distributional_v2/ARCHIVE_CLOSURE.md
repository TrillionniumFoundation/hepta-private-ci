# Final archive closure

`archive_closure.py` is a standard-library auditor. It never imports Torch or
loads NPZ arrays. It reads completed evidence, hashes files in bounded blocks,
and publishes `artifacts/ARCHIVE_COMPLETION.json` only after every required
check succeeds. The schema is `hcsn-v2-archive-closure.v1`. The completion file
is immutable and is published with an exclusive atomic link.

## Completion order

1. Finish all 176 main searches and all 18 LIF pairs. Preserve the frozen main
   strict audit exactly: **175 valid, one invalid**, with its original FSDD
   Transformer cross-entropy-summary failure. Independently complete all 176
   integrity audits under `CONTENT_SUPPLEMENT001_PROTOCOL.json`; the supplement
   must be explicitly post hoc, have 176 valid and zero invalid, preserve the
   statistical gates, and have no common-initialization mismatches. Both exact
   identities and the failed original gate are recorded in the final closure;
   a supplemental pass is never relabeled as a strict pass.
   The main and LIF schedulers and both analysis processes must have exited
   successfully. Wait for the existing LIF analysis watcher to finalize its
   own CPU record; an active heartbeat cannot be substituted.
2. Create the explicit LIF cost bindings and run the adapter below. This is an
   on-demand adapter, not a second analysis watcher. Its completed receipt is
   also a gate for the registered scaling study.
3. Preserve `SCALING001_PROTOCOL.json` and its preflight, and record that the
   original scaling study was not executed because its strict-audit admission
   failed. Complete all 30 separately registered `SCALING002_PROTOCOL.json`
   CPU scaling attempts using the same cases, randomness, measurement rules,
   preflight, and frozen benchmark code. Only the admission identity changes.
   The models are
   `distribution_free_dual`, `two_gates`, and `transformer`. There are six
   lengths from 16 through 512 at width 32/depth 1, plus four width/depth cases
   at length 64, for each model. A recorded resource failure is valid negative
   evidence: it must have a failure file, matching identity and exit status,
   and remain in the complete 30-case inventory. Closure does not relabel
   failed cases as successful measurements.
4. Finish the main checkpoint watcher and the three ordinary bundles for LIF,
   main metadata, and auxiliary evidence. Keep their wrapper sources unchanged
   between sealing and closure. The checkpoint watcher's final coverage must
   be exactly the 176 registered IDs, with no duplicate selected runs.
5. Run the final auditor once. Its own execution receipt and any enclosing
   `wait4` measurement are separate publication artifacts and are not inserted
   back into the bundles whose hashes it certifies.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.archive_closure --output experiments/hcsn_distributional_v2/results/archive_closure001
```

Do not add further bundle manifests after closure. README, final reports, and
final cost outputs can be published directly in Git without introducing a
recursive archive/closure/cost dependency.

## Required bundle names

The auditor requires these six names and every successful `content002_runs_*`
manifest declared by the checkpoint watcher:

- `task_value_and_control002`
- `content_aborted001`
- `execution_v2_001`
- `lif_supplement001_evidence`
- `content002_metadata`
- `v2_auxiliary_evidence`

Every formal schema-matching manifest enters the closure. Each part's size,
SHA-256 and recorded Git blob hash are checked, as is the combined compressed
stream hash. Restore seals must bind the same archive and member count and
the unchanged bundler/packer source hashes. Main and generic bundle selection
manifests must exactly match their complete member inventories. Generic outer
receipts come from `results/evidence_sealing/<name>/EXECUTION.json`; main-run
outer receipts come from `results/content_checkpoint_archives/receipts/`.
The three early bundles have only their original seal self-CPU measurements;
no missing complete outer measurement is invented.

The member union may repeat identical bytes at an identical path. A size or
hash conflict is rejected. All files in the 176 main run directories, all
files in the 18 LIF run directories, and their corresponding process logs must
be covered byte-for-byte. The full `results/scaling002/` tree must also be
covered, including all 30 case directories and all failed-case evidence.
The unexecuted `results/scaling001/` tree and the original
`results/scaling_preflight001/` tree remain required historical evidence.
Internal `work/` trees are not traversed as campaign evidence.

## Required proof files in the archive union

These are exact paths relative to `experiments/hcsn_distributional_v2/`:

| Group | Required paths |
|---|---|
| Canonical registrations | `CONTENT002_PROTOCOL.json`, `CONTENT_SUPPLEMENT001_PROTOCOL.json`, `LIF_SUPPLEMENT001_PROTOCOL.json`, `SCALING001_PROTOCOL.json`, `SCALING002_PROTOCOL.json` |
| Checkpoint closure | `results/content_checkpoint_archives/COMPLETE.json` |
| Main completion | `results/content002/COMPLETE.json`, `results/content002/SCHEDULER_EXECUTION.json` |
| Main analysis | `results/content_analysis002/ANALYSIS.json`, `results/content_analysis002/EXECUTION.json`, `results/content_analysis002.log` |
| Supplemental analysis | `results/content_analysis_supplement001/ANALYSIS.json` and `results/content_analysis_supplement001_execution/{EXECUTION.json,REQUEST.json,process.log}` |
| LIF completion | `results/lif_supplement001/COMPLETE.json`, `results/lif_supplement001/SCHEDULER_EXECUTION.json` |
| LIF analysis | `results/lif_analysis001/ANALYSIS.json` |
| LIF normalized costs | `results/lif_cost_receipts001/RECEIPTS.json` and each of its three original receipt paths |
| Scaling002 | `results/scaling002/COMPLETE.json`, `results/scaling002/SUITE_EXECUTION.json`, and every other regular file in `results/scaling002/` |
| Original scaling001 | `results/scaling001/NOT_EXECUTED.json`, the complete original study tree, and the complete `results/scaling_preflight001/` tree |

For the three LIF original receipts, take the exact paths from
`RECEIPTS.json.scopes[*].receipt`, stripping the repository prefix
`experiments/hcsn_distributional_v2/` for package-relative inclusion. The
scheduler path is fixed above. The final analysis watcher and analyzer outer
paths are bound to their actual immutable originals, not guessed from a
similarly named body timer. Including the complete LIF study, analysis, and
normalization directories covers these paths.

Registered root Python files and frozen model/kernel files are rehashed
against their registrations and selections. Their canonical root paths are
not additionally required in the archive member union: they can be published
directly in Git, while the experiment source snapshots remain archived.
The auditor, final README/report, and final cost outputs likewise are not
required to archive themselves.

## LIF cost adapter

Copy `LIF_COST_BINDINGS_TEMPLATE.json` to a new bindings file. Inspect the
actual successful analyzer outer receipt and the final watcher file, then
replace the explicit placeholders with their exact original paths and JSON
pointers. The scheduler's complete CPU field is
`/complete_child_cpu_seconds` and its success field is `/exit_code`, equal to
integer zero. The template deliberately cannot pass while placeholders remain.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.lif_cost_receipts --bindings PATH_TO_COMPLETED_BINDINGS_JSON --output experiments/hcsn_distributional_v2/results/lif_cost_receipts001
```

The adapter verifies the 18-pair analysis, explicit original-plus-supplemental
main admission, original hashes, exact pointer
values and types, successful exit/status conditions, and the frozen protocol.
It emits exactly three core scopes: complete LIF scheduler tree, complete
analyzer child, and one final watcher-self measurement. The independent outer
scheduler-supervisor window is listed under `additional_measured_windows`
with `measurement_kind=partial_process_body_timer`; it is charged only by its
separately declared extra-cost scope, not as a fourth core scope.

Failed adapter attempts retain `FAILED_EXECUTION_<id>.json` and do not create
`RECEIPTS.json`; a corrected attempt can use the same fixed output directory.
Successful normalization is immutable. Keep both `lif_cost_receipts.py` and
`archive_closure.py` unchanged after actual normalization, since the
normalized record binds their source hashes.
Its `main_admission` records the original failed strict audit and the separate
complete producer-exact supplement, with their exact paths and hashes.

The adapter has no background loop or children. Its own self-CPU through the
final receipt is in `results/lif_cost_receipts001/EXECUTION.json`. Prefer an
enclosing `wait4` receipt for the complete adapter process; if one is recorded,
the adapter's internal clock is nested and must not be added again.

## Validation scope

The isolated fixture in `results/archive_closure_tests001/` exercised seven
real pack/restore bundles, exact 176/18 coverage, negative integrity cases,
and a 30-case diagnostic with an explicitly preserved failed case. Its
earlier scaling-model assumption is recorded in `SCOPE_NOTE.json` and was
corrected without altering those historical test receipts.

`results/archive_closure_scaling_interface002/` checks the actual registered
scaling producer's 30 cases against the corrected consumer and rejects the
old LIF substitution. `results/archive_closure_gate_tests003/` tests the added
initialization/exit/cost-pointer gates, rejects an active watcher, verifies a
successful retry, and rejects both a forged CPU value and a boolean supplied
as an integer exit status. These are synthetic contract tests, not model
quality results. The real final closure is a separate later invocation.

The pre-supplement consumers and documents are preserved byte-for-byte under
`results/admission_consumer004/before/`. The later narrow admission validation
tests the new original/supplement identities and scaling001/scaling002 handoff;
it does not rerun mathematics, training, or the earlier bundle fixtures.
