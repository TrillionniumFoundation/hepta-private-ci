# Observed CPU lower bound

Receipt coverage status: **incomplete**.

Observed lower bound: **2800.711608450 CPU seconds**.

This is a sum of the explicit disjoint scopes below. `complete` describes required receipt coverage only. Unmeasured development, downloads, source editing, process remainders and work after this cutoff remain unknown; they are not zero. Wall time, hypothetical deployment scenarios, historical v1 training and reused LIF comparator training are excluded.

Cutoff: 2026-10-30T02:28:52.255934+00:00. No predictions, heldout scores, weights or policy choices were read by this audit.

## Additive groups

| Group | Observed CPU lower bound (seconds) |
| --- | ---: |
| artifact_engineering | 0.698336961 |
| artifacts | 142.336454914 |
| calibration | 0.543163173 |
| content_aborted | 2227.408732000 |
| content_engineering | 106.335585150 |
| cost_audit | 0.660164458 |
| distributional_native | 36.833268920 |
| figures_and_reports | 5.435565561 |
| lif | 15.736134000 |
| numerical | 42.026106000 |
| reproduction | 1.429715194 |
| runtime | 101.855430207 |
| setup | 12.852884250 |
| task | 106.560067662 |

## Explicit additive scopes

| Scope | Measurement | Seconds | Receipt field |
| --- | --- | ---: | --- |
| setup_original_data | complete_process_tree_wait4 | 0.481289000 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/records/0/child_cpu_seconds` |
| setup_auxiliary_evidence | complete_process_tree_wait4 | 4.091035000 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/records/1/child_cpu_seconds` |
| setup_study001_evidence | complete_process_tree_wait4 | 7.510866000 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/records/2/child_cpu_seconds` |
| setup_conditional001_evidence | complete_process_tree_wait4 | 0.415431000 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/records/3/child_cpu_seconds` |
| setup_equal_updates_core002_evidence | complete_process_tree_wait4 | 0.346230000 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/records/4/child_cpu_seconds` |
| setup_coordinator | partial_process_body_timer | 0.008033250 | `experiments/hcsn_distributional_v2/results/setup001/RESTORE.json#/coordinator_cpu_through_cutoff` |
| numerical_aggregate | explicit_disjoint_receipt_aggregate | 40.282132000 | `experiments/hcsn_distributional_v2/results/NUMERICAL_COSTS.json#/totals/sum_of_disjoint_recorded_cpu_scopes_lower_bound` |
| content_engineering | explicit_disjoint_receipt_aggregate | 101.787531150 | `experiments/hcsn_distributional_v2/results/content_engineering_COSTS.json#/recorded_engineering_cpu_lower_bound_seconds` |
| lif_engineering | complete_process_tree_wait4 | 15.736134000 | `experiments/hcsn_distributional_v2/results/lif_supplement001/ENGINEERING_COSTS.json#/complete_prelaunch_child_cpu_seconds` |
| policy_gap | complete_process_tree_wait4 | 1.743974000 | `experiments/hcsn_distributional_v2/results/policy_gap001/EXECUTION.json#/complete_child_cpu_seconds` |
| content_integrity_pilot | complete_process_tree_wait4 | 4.548054000 | `experiments/hcsn_distributional_v2/results/content_integrity_pilot002_EXECUTION.json#/complete_child_cpu_seconds` |
| content001_aborted | complete_process_tree_wait4 | 2227.408732000 | `experiments/hcsn_distributional_v2/results/content001/SCHEDULER_EXECUTION.json#/wait4_total_cpu_seconds` |
| runtime_suite | complete_process_tree_wait4 | 98.293059000 | `experiments/hcsn_distributional_v2/results/runtime001/SUITE_EXECUTION.json#/complete_child_cpu_seconds` |
| runtime_tests | complete_process_tree_wait4 | 3.379525000 | `experiments/hcsn_distributional_v2/results/runtime_tests001_EXECUTION.json#/complete_child_cpu_seconds` |
| runtime_review | process_self_cpu_through_receipt | 0.182846207 | `experiments/hcsn_distributional_v2/results/runtime_review001/EXECUTION.json#/whole_analysis_self_cpu_seconds` |
| task_failed001 | complete_process_tree_wait4 | 5.395364000 | `experiments/hcsn_distributional_v2/results/task_value001/CAMPAIGN_EXECUTION.json#/complete_child_cpu_seconds` |
| task_campaign002 | complete_process_tree_wait4 | 97.562924000 | `experiments/hcsn_distributional_v2/results/task_value002/CAMPAIGN_EXECUTION.json#/complete_child_cpu_seconds` |
| task_analysis_parent | process_self_cpu_through_receipt | 2.473637276 | `experiments/hcsn_distributional_v2/results/task_value002/ANALYSIS_PARENT_EXECUTION.json#/whole_parent_self_cpu_seconds_through_report` |
| task_tabular_addendum | process_self_cpu_through_receipt | 0.057944109 | `experiments/hcsn_distributional_v2/results/task_tabular_cost001/EXECUTION.json#/whole_analysis_self_cpu_seconds` |
| task_independent_review | process_self_cpu_through_receipt | 1.070198277 | `experiments/hcsn_distributional_v2/results/independent_execution_review001/EXECUTION.json#/analysis_self_cpu_seconds_from_process_start` |
| native_coordinator | process_self_cpu_through_receipt | 2.226265920 | `experiments/hcsn_distributional_v2/results/distributional_native001/COORDINATOR_EXECUTION.json#/whole_self_cpu_seconds_through_cutoff` |
| calibration_child | complete_process_tree_wait4 | 0.402218000 | `experiments/hcsn_distributional_v2/results/task_future_calibration001/EXECUTION.json#/complete_child_cpu_seconds` |
| calibration_parent | process_self_cpu_through_receipt | 0.140945173 | `experiments/hcsn_distributional_v2/results/task_future_calibration001/PARENT_EXECUTION.json#/whole_self_cpu_seconds_through_cutoff` |
| reproduction_list_child | complete_process_tree_wait4 | 0.149942000 | `experiments/hcsn_distributional_v2/reproduction_receipts/list001/EXECUTION.json#/complete_worker_cpu_seconds` |
| reproduction_list_parent | process_self_cpu_through_receipt | 0.682622001 | `experiments/hcsn_distributional_v2/reproduction_receipts/list001/EXECUTION.json#/coordinator_whole_self_cpu_seconds_through_cutoff` |
| reproduction_smoke_child | complete_process_tree_wait4 | 0.555698000 | `experiments/hcsn_distributional_v2/reproduction_receipts/restore_smoke001/EXECUTION.json#/complete_child_cpu_seconds` |
| reproduction_smoke_parent | process_self_cpu_through_receipt | 0.041453193 | `experiments/hcsn_distributional_v2/reproduction_receipts/restore_smoke001/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| native_prepare | complete_process_tree_wait4 | 5.723704000 | `experiments/hcsn_distributional_v2/results/distributional_native001/prepare_EXECUTION.json#/complete_child_cpu_seconds` |
| native_evaluate | complete_process_tree_wait4 | 9.467432000 | `experiments/hcsn_distributional_v2/results/distributional_native001/evaluate_EXECUTION.json#/complete_child_cpu_seconds` |
| native_recovery_reference | complete_process_tree_wait4 | 4.102601000 | `experiments/hcsn_distributional_v2/results/distributional_native001/recovery_reference_EXECUTION.json#/complete_child_cpu_seconds` |
| native_recovery_active | complete_process_tree_wait4 | 3.542109000 | `experiments/hcsn_distributional_v2/results/distributional_native001/recovery_active_EXECUTION.json#/complete_child_cpu_seconds` |
| native_resume_active | complete_process_tree_wait4 | 4.142465000 | `experiments/hcsn_distributional_v2/results/distributional_native001/resume_active_EXECUTION.json#/complete_child_cpu_seconds` |
| native_recovery_quiet | complete_process_tree_wait4 | 4.007259000 | `experiments/hcsn_distributional_v2/results/distributional_native001/recovery_quiet_EXECUTION.json#/complete_child_cpu_seconds` |
| native_resume_quiet | complete_process_tree_wait4 | 3.621433000 | `experiments/hcsn_distributional_v2/results/distributional_native001/resume_quiet_EXECUTION.json#/complete_child_cpu_seconds` |
| figures001 | process_self_cpu_through_receipt | 5.435565561 | `experiments/hcsn_distributional_v2/results/figures001/MANIFEST.json#/whole_self_cpu_seconds_through_render` |
| content_checkpoint_archives_tests001_child | complete_process_tree_wait4 | 0.108455000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives_tests001/EXECUTION.json#/cpu_seconds_including_children` |
| content_checkpoint_archives_tests001_parent | process_self_cpu_through_receipt | 0.040404352 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives_tests001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| content_checkpoint_archives_tests002_child | complete_process_tree_wait4 | 0.503141000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives_tests002/EXECUTION.json#/cpu_seconds_including_children` |
| content_checkpoint_archives_tests002_parent | process_self_cpu_through_receipt | 0.046336609 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives_tests002/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| archive_content002_runs_000 | complete_process_tree_wait4 | 72.052727000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_000.json#/cpu_seconds_including_children` |
| archive_content_aborted001 | process_self_cpu_through_receipt | 35.146398380 | `experiments/hcsn_distributional_v2/artifacts/content_aborted001_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| archive_execution_v2_001 | process_self_cpu_through_receipt | 2.843813874 | `experiments/hcsn_distributional_v2/artifacts/execution_v2_001_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| archive_task_value_and_control002 | process_self_cpu_through_receipt | 32.293515660 | `experiments/hcsn_distributional_v2/artifacts/task_value_and_control002_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| cost_audit_tests001_child | complete_process_tree_wait4 | 0.116648000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests001/EXECUTION.json#/complete_child_cpu_seconds` |
| cost_audit_tests001_parent | process_self_cpu_through_receipt | 0.048211649 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests001/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| campaign_costs_tests002_child | complete_process_tree_wait4 | 0.103825000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests002/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_tests002_parent | process_self_cpu_through_receipt | 0.041085451 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests002/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| campaign_costs_probe001_child | complete_process_tree_wait4 | 0.052604000 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe001/WRAPPER_EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_probe001_parent | process_self_cpu_through_receipt | 0.046130803 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe001/WRAPPER_EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| campaign_costs_tests003_child | complete_process_tree_wait4 | 0.065110000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests003/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_tests003_parent | process_self_cpu_through_receipt | 0.042385892 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests003/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| campaign_costs_probe002_child | complete_process_tree_wait4 | 0.107000000 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe002/WRAPPER_EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_probe002_parent | process_self_cpu_through_receipt | 0.037163663 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe002/WRAPPER_EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |

Full receipt SHA-256 bindings, original component reconciliations, scope exclusions and missing inputs are in LEDGER.json. Aggregate components are validation evidence and are never added a second time.

## Missing required inputs

- `experiments/hcsn_distributional_v2/artifacts/ARCHIVE_COMPLETION.json`
- `experiments/hcsn_distributional_v2/results/content002/COMPLETE.json`
- `experiments/hcsn_distributional_v2/results/content002/SCHEDULER_EXECUTION.json`
- `experiments/hcsn_distributional_v2/results/content_analysis002/EXECUTION.json`
- `experiments/hcsn_distributional_v2/results/lif_cost_receipts001/RECEIPTS.json`
- `results/content_checkpoint_archives/instances/*_EXECUTION.json (final watcher self CPU)`

## Unknown and excluded work

- Remote restoration/download and environment installation CPU were not fully receipted; remote wall time is not converted to CPU.
- Untimed development, source inspection/editing, early numerical smoke, compilation, and partial timer remainders are unknown.
- Supervisor/import/serialization/exit work outside recorded windows or self-CPU cutoffs is unknown.
- Failed task001's early supervisor snapshot is not added without a proven independent process scope; the full failed child tree is charged.
- Publishing, later archive/report updates, this ledger generation and all work after the stated cutoff are outside this lower bound.

The ledger generator records its own self CPU separately in EXECUTION.json after this ledger cutoff. This avoids self-referential cost totals. Earlier probes or extra reports enter a later ledger only through an explicit additional-scope declaration.
