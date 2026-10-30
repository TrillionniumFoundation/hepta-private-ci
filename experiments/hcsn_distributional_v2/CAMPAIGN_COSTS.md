# Campaign CPU evidence contract

`campaign_costs.py` produces an **observed lower bound**, in CPU seconds, from an explicit list of mutually disjoint recorded process scopes. It never imports a model, loads weights or predictions, repeats training, selects a policy, or converts a hypothetical deployment scenario into a historical charge.

The output has three files: `LEDGER.json`, `REPORT.md`, and the generator's separate `EXECUTION.json`. The source is copied into `source/`. Output directories must be new. Existing research files are read only.

## Consumer interface and completeness

The JSON fields intended for the final report are:

| Field | Meaning |
| --- | --- |
| `status` | `complete` or `incomplete`: whether the explicitly required receipt set is available and has passed accounting checks. |
| `observed_cpu_lower_bound_seconds` | Sum of additive `scope_rows`, reconciled against `by_group`. Always an observed lower bound. |
| `coverage_cutoff_utc` | Timestamp at which this inventory was assembled. |
| `missing_required_inputs` | Required receipts or final watcher records absent at this cutoff. A final report must require an empty list. |
| `scope_rows` | Exact additive scope, measurement class, original receipt path, SHA-256, JSON pointer and amount. |
| `input_receipts` | All original and aggregate evidence inputs, with file SHA-256 and byte count. |
| `unknown_additional_cpu_seconds` | Always `null`. Unknown work is not assigned a fabricated zero. |

`complete` does **not** mean complete research expenditure. Development without receipts, downloads, editing, compilation, wrapper startup/exit beyond recorded windows, and later publication work remain unknown. No energy consumption or dollar cost has been measured by this ledger.

The audit distinguishes full process-tree `wait4` receipts, process-self CPU through a recorded cutoff, and local process-body timers. The numerical/content engineering aggregates mix these kinds; their original component receipts are reconciled and listed as **nested verification evidence**, never additional charges.

## Commands

Run from the checkout root. This tool needs only the Python standard library. No Torch environment is needed.

```bash
python -m experiments.hcsn_distributional_v2.campaign_costs \
  --allow-incomplete \
  --output experiments/hcsn_distributional_v2/results/campaign_costs_NEW_PROBE

python -m experiments.hcsn_distributional_v2.campaign_costs \
  --archive-completion artifacts/ARCHIVE_COMPLETION.json \
  --extra-scopes experiments/hcsn_distributional_v2/results/campaign_costs_extra_scopes006.json \
  --output experiments/hcsn_distributional_v2/results/campaign_costs_NEW_FINAL
```

The first form permits a deliberately incomplete preview. The second exits with code 2 if required inputs remain absent, while retaining its incomplete output. Invalid hashes, inconsistent totals, duplicated receipt fields, conflicting archive members or malformed completion declarations are errors even with `--allow-incomplete`.

Paths in original historical command strings are not executed. Receipt paths under a moved checkout are resolved against the current repository. `--archive-completion` is package-relative by default; a repository-relative path beginning with `experiments/` or an absolute path in the current repository is also accepted.

## Fixed input scopes

All paths below are relative to `experiments/hcsn_distributional_v2/`. A slash-prefixed field is a JSON pointer. The code records each field's original file SHA.

| Group | Original input and additive field |
| --- | --- |
| Setup restoration | `results/setup001/RESTORE.json`: each `/records/i/child_cpu_seconds` plus the separate `/coordinator_cpu_through_cutoff`. `REMOTE_RESTORE.json` reports wall time, not additive CPU. |
| Numerical work | `results/NUMERICAL_COSTS.json#/totals/sum_of_disjoint_recorded_cpu_scopes_lower_bound`; original child/wrapper/partial receipts are SHA-bound and their sum is checked. Independent `results/policy_gap001/EXECUTION.json#/complete_child_cpu_seconds` is added separately. |
| Content engineering | `results/content_engineering_COSTS.json#/recorded_engineering_cpu_lower_bound_seconds`; its complete children and partial intervals are reconciled against original fields. `content_tests004_EXECUTION.json` and `content_domain_preflight003_EXECUTION.json` use `/child_cpu_seconds`; earlier complete receipts use `/complete_child_cpu_seconds`. The independent integrity pilot uses `results/content_integrity_pilot002_EXECUTION.json#/complete_child_cpu_seconds`. |
| Aborted content001 | `results/content001/SCHEDULER_EXECUTION.json#/wait4_total_cpu_seconds`. This contains its started workers and their internal training/evaluation work. |
| Main content002 | `results/content002/SCHEDULER_EXECUTION.json#/wait4_total_cpu_seconds`; `COMPLETE.json` supplies the 176-worker accounting check only. `results/content_analysis002/EXECUTION.json` contributes `/complete_child_cpu_seconds` and separate `/watcher_self_cpu_seconds`. |
| LIF engineering | `results/lif_supplement001/ENGINEERING_COSTS.json#/complete_prelaunch_child_cpu_seconds`, reconciled against four original complete children. |
| LIF training/analysis | `results/lif_cost_receipts001/RECEIPTS.json` is the explicit normalization map described below. Reused main-study comparator training is never charged again. |
| Runtime | `results/runtime001/SUITE_EXECUTION.json#/complete_child_cpu_seconds`; `results/runtime_tests001_EXECUTION.json#/complete_child_cpu_seconds`; `results/runtime_review001/EXECUTION.json#/whole_analysis_self_cpu_seconds`. All case/resume children in the suite are nested. |
| Task value | Failed001 and successful002 `CAMPAIGN_EXECUTION.json#/complete_child_cpu_seconds`; successful002 `ANALYSIS_PARENT_EXECUTION.json#/whole_parent_self_cpu_seconds_through_report`; tabular addendum `EXECUTION.json#/whole_analysis_self_cpu_seconds`; independent review `EXECUTION.json#/analysis_self_cpu_seconds_from_process_start`. `REPORT_EXECUTION`'s body is inside the whole parent. |
| Trained v2 native | Seven `results/distributional_native001/*_EXECUTION.json#/complete_child_cpu_seconds` phase workers plus `COORDINATOR_EXECUTION.json#/whole_self_cpu_seconds_through_cutoff`. Their native descendants are nested; backbone training belongs to content002. |
| Future-value calibration | `results/task_future_calibration001/EXECUTION.json#/complete_child_cpu_seconds` plus `PARENT_EXECUTION.json#/whole_self_cpu_seconds_through_cutoff`. |
| Reproduction | `reproduction_receipts/list001/EXECUTION.json` contributes `/complete_worker_cpu_seconds` and `/coordinator_whole_self_cpu_seconds_through_cutoff`; `restore_smoke001/EXECUTION.json` contributes `/complete_child_cpu_seconds` and `/outer_parent_self_cpu_seconds_to_cutoff`. Nested helper receipts share one smoke interpreter and are not additive. |
| Figures | Existing `results/figures001/MANIFEST.json#/whole_self_cpu_seconds_through_render`; later rendering/report invocations can enter through an explicit extra-scope manifest. |
| Archive engineering | Existing `results/content_checkpoint_archives_tests001/EXECUTION.json` and `tests002/EXECUTION.json`: `/cpu_seconds_including_children` plus separate `/supervisor_self_cpu_seconds_through_receipt`. The failed first fixture is retained and charged. |
| Registered scaling suite | When `SCALING001_PROTOCOL.json` exists, `results/scaling001/SUITE_EXECUTION.json` is required: `/complete_child_cpu_seconds` plus separate `/supervisor_self_cpu_seconds_through_cutoff`. `COMPLETE.json`, all30 original case receipts and the protocol/source binding are reconciled. Their worker totals are nested and cannot be added through extra scopes. The independent preparation costs are in extra006. |

### LIF original-field adapter

The LIF outer launchers were started before this ledger was written. Their future raw field names must not be guessed. Once the original final receipts exist, a new read-only map at `results/lif_cost_receipts001/RECEIPTS.json` must have `schema: hcsn-lif-cost-receipts.v1`, `status: completed`, and exactly three `scopes`:

- `lif_scheduler`: complete scheduler `wait4`, including its 18 new workers.
- `lif_analysis`: complete independent analyzer `wait4`.
- `lif_analysis_watcher`: the final watcher self-CPU cutoff, separate from its analyzer child.

Each scope declares `receipt`, `receipt_sha256`, `field`, `cpu_seconds`, `measurement_kind`, `success_field`, `success_value`, and a plain-language `scope`. The first two measurement kinds are `complete_process_tree_wait4`; the third is `process_self_cpu_through_receipt`. The ledger rereads each **original** file, verifies its SHA and CPU field, checks the mapped amount, and verifies the exact original success field/value and its JSON type. The map itself adds no CPU. The scheduler's original receipt path is `results/lif_supplement001/SCHEDULER_EXECUTION.json`; its real success field is `/exit_code == 0`, while the main content scheduler uses `/returncode == 0`. Its18-worker sum is checked using `COMPLETE.json` and remains nested. The separately measured LIF outer-supervisor window `/outer_supervisor_self_window_cpu_seconds` is included through extra006 as a **partial self window**, not whole-process self CPU.

## Archive cost selection and final closure

Only manifests with schema `hcsn-evidence-bundle.v1` under `artifacts/` are discovered. Each requires a matching `<name>_EXECUTION.json` seal, matching archive SHA, and a prior successful `verified_restore` member count. The cost audit hashes metadata receipts; it does not repeat decompression or reread every payload.

For each bundle independently:

1. If `results/content_checkpoint_archives/receipts/<name>.json` exists, use its full `/cpu_seconds_including_children`. Verify `bundle_name`, `manifest_path`, successful return code, user/system sum and coverage of the seal's inner self timer. Do not also add pack/restore/body/seal timers.
2. A generic staged publisher instead writes `results/evidence_sealing/<name>/EXECUTION.json`, with schema `hcsn-v2-staged-bundle-execution.v1`. Use `/complete_archive_child_cpu_seconds` for its complete pack/restore child, replacing the nested seal timer. Add its independent `/coordinator_whole_self_cpu_seconds_through_cutoff` once. The same bundle cannot simultaneously have a checkpoint-watcher and generic-publisher enclosing receipt.
3. If neither enclosing receipt exists, use the seal's `/whole_process_self_cpu_seconds_through_seal`, explicitly a self-CPU cutoff with unknown remainder.
4. A failed packing invocation has an outer receipt but no published manifest. Charge that failed child once, plus its separate coordinator where recorded. Its failed work stays outside the successful artifact directory.
5. Add each final `instances/*_EXECUTION.json#/own_cpu_seconds` once. Never sum cumulative heartbeat snapshots.

Final receipt coverage requires `artifacts/ARCHIVE_COMPLETION.json` with `schema: hcsn-v2-archive-closure.v1`, `status: completed`, and `bundles[{manifest, manifest_sha256, archive_sha256, members, parts}]`. For each bundle with an enclosing receipt, also supply `outer_receipt` and `outer_receipt_sha256`; these must match the actual selected publisher receipt. The manifest set must exactly match discovered successful bundles. `members` and `parts` are integer counts. `main_run_coverage.expected`, `.completed` and `.unique` must each equal 176. The manifest union must contain the five original identity/selection/summary/checkpoint/execution files for all 176 main and 18 LIF completed job identities, with no conflicting SHA for any shared path. The union can contain repeated identical files; copying evidence does not repeat the original experiment's compute charge.

## Extra independent scopes and generation cutoff

An extra-scope file uses schema `hcsn-explicit-extra-costs.v1` and a `scopes` array. Each entry requires `scope_id`, `group`, original `path`, `receipt_sha256`, `field`, `measurement_kind`, and `disjoint_scope_explanation`. It is an explicit reviewed addition, not a recursive CPU-field search. Reusing an already charged field or an aggregate's verified nested field is rejected.

`results/campaign_costs_extra_scopes006.json` retains the earlier cost-audit test/preview invocations and adds the seal smoke, closure tests, actual scaling producer/consumer interface test, measured LIF supervisor window, scaling preparation and two targeted cost-accounting regressions. Its25 independent scopes total **12.898198371 CPU seconds observed lower bound**. The original extra004 remains preserved with its12 earlier scopes. Future figure/report generation can be appended in a **new** manifest, retaining every original receipt and old manifest. The formal scaling suite is already required by the fixed ledger when its protocol exists; do not append its cost again. Never modify a sealed earlier preview to include later costs.

The emitted ledger's own `EXECUTION.json` lies after that ledger's accounting cutoff. It is deliberately outside its own sum. A later ledger can count the preceding generator's full outer `WRAPPER_EXECUTION.json` and supervisor self CPU once; the earlier generator's inner self timer is then nested. This avoids recursive self-charging. The same cutoff rule applies to a final report produced after the ledger it cites.

## Completed validation and incomplete preview

Eleven tiny-fixture tests cover raw SHA binding, nonnegative finite CPU values, rejected reuse of nested fields, numerical aggregate reconciliation, the mixed original content receipt field names, failed packing retention, seal/restore binding, per-bundle outer-over-inner replacement, the staged publisher's separate child/coordinator scopes, the original LIF `/exit_code` and success-pointer contract, and containment of the newly registered scaling suite. They run under `unittest` without loading experiment data:

```bash
python -m unittest experiments.hcsn_distributional_v2.campaign_costs_tests -v
```

`results/campaign_costs_tests001` preserves the initial seven tests. `tests002` preserves all eight after the content-field regression; `tests003` preserves all nine after the staged-publisher adapter. After LIF's actual scheduler receipt became available, `tests004` ran the new targeted exit-field/success-pointer regression successfully. `tests005` then passed the targeted30-receipt scaling containment regression, including rejection of a duplicate nested-worker charge. All prior source snapshots remain unchanged. `campaign_costs_probe001` preserves the failed original-field lookup, source snapshot, log and complete outer cost receipt; it produced no ledger. `campaign_costs_probe002` is the earlier successful **incomplete** preview: 48 additive scopes, 61 SHA-bound input files, **2728.407221895 CPU seconds observed lower bound**. `campaign_costs_probe003`, before the LIF exit-field/scaling additions, adds the completed first content checkpoint bundle via its outer receipt: **2800.711608450 CPU seconds observed lower bound**. Pending main scheduler/analysis, LIF final mapping, archive-watcher completion and archive closure remain explicitly absent from that historical preview. Neither preview is a final campaign accounting claim. Each probe's own execution lies after its accounting cutoff; the current source additionally requires the registered scaling suite's final receipts.
