# Observed CPU lower bound

Receipt coverage status: **complete**.

Observed lower bound: **30939.006142960 CPU seconds**.

This is a sum of the explicit disjoint scopes below. `complete` describes required receipt coverage only. Unmeasured development, downloads, source editing, process remainders and work after this cutoff remain unknown; they are not zero. Wall time, hypothetical deployment scenarios, historical v1 training and reused LIF comparator training are excluded.

Cutoff: 2026-10-30T06:02:33.634266+00:00. This audit uses receipt and integrity-admission metadata, not prediction arrays, weights, quality-based policy selection, or new inference.

The original strict content audit remains175 valid/1 invalid. A separately registered post-hoc producer-exact audit has176 valid/0 invalid and retains all scientific comparisons. SCALING001 was not executed. All30 SCALING002 workers succeeded, but its original summary failed on a zero denominator; a separate read-only reconstruction preserves those timings and the failed suite. Both analysis processes, the failed suite and its reconstruction remain charged independently.

## Additive groups

| Group | Observed CPU lower bound (seconds) |
| --- | ---: |
| artifact_closure | 2.993132526 |
| artifact_engineering | 8.249867720 |
| artifact_planning | 7.097710677 |
| artifacts | 501.957142884 |
| calibration | 0.543163173 |
| content_aborted | 2227.408732000 |
| content_engineering | 106.335585150 |
| content_integrity_diagnostics | 8.650788308 |
| content_integrity_engineering | 3.132267328 |
| content_main | 25334.966249181 |
| content_supplemental_audit | 23.109847696 |
| cost_audit | 1.883063863 |
| cost_normalization | 0.198435073 |
| distributional_native | 36.833268920 |
| figures_and_reports | 9.736769455 |
| lif | 2293.030240971 |
| numerical | 42.026106000 |
| report_engineering | 0.432540537 |
| reproduction | 2.179465121 |
| runtime | 101.855430207 |
| scaling | 105.791522290 |
| scaling_engineering | 1.181861968 |
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
| content002_scheduler | complete_process_tree_wait4 | 25305.600842000 | `experiments/hcsn_distributional_v2/results/content002/SCHEDULER_EXECUTION.json#/wait4_total_cpu_seconds` |
| content002_analysis | complete_process_tree_wait4 | 28.985444000 | `experiments/hcsn_distributional_v2/results/content_analysis002/EXECUTION.json#/complete_child_cpu_seconds` |
| content002_analysis_watcher | process_self_cpu_through_receipt | 0.379963181 | `experiments/hcsn_distributional_v2/results/content_analysis002/EXECUTION.json#/watcher_self_cpu_seconds` |
| content_supplement_analysis | complete_process_tree_wait4 | 23.066859000 | `experiments/hcsn_distributional_v2/results/content_analysis_supplement001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| content_supplement_supervisor | process_self_cpu_through_receipt | 0.042988696 | `experiments/hcsn_distributional_v2/results/content_analysis_supplement001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
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
| lif_scheduler | complete_process_tree_wait4 | 2266.716221000 | `experiments/hcsn_distributional_v2/results/lif_supplement001/SCHEDULER_EXECUTION.json#/complete_child_cpu_seconds` |
| lif_analysis | complete_process_tree_wait4 | 9.848573000 | `experiments/hcsn_distributional_v2/results/lif_supplement001/ANALYSIS_OUTER_EXECUTION.json#/complete_child_cpu_seconds` |
| lif_analysis_watcher | process_self_cpu_through_receipt | 0.726634799 | `experiments/hcsn_distributional_v2/results/lif_supplement001/ANALYSIS_OUTER_EXECUTION.json#/watcher_self_cpu_seconds` |
| archive_content002_metadata | complete_process_tree_wait4 | 0.728089000 | `experiments/hcsn_distributional_v2/results/evidence_sealing/content002_metadata/EXECUTION.json#/complete_archive_child_cpu_seconds` |
| archive_content002_runs_000 | complete_process_tree_wait4 | 72.052727000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_000.json#/cpu_seconds_including_children` |
| archive_content002_runs_001 | complete_process_tree_wait4 | 61.009474000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_001.json#/cpu_seconds_including_children` |
| archive_content002_runs_002 | complete_process_tree_wait4 | 46.726664000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_002.json#/cpu_seconds_including_children` |
| archive_content002_runs_003 | complete_process_tree_wait4 | 84.551250000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_003.json#/cpu_seconds_including_children` |
| archive_content002_runs_004 | complete_process_tree_wait4 | 77.940543000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_004.json#/cpu_seconds_including_children` |
| archive_content002_runs_005 | complete_process_tree_wait4 | 13.284245000 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/receipts/content002_runs_005.json#/cpu_seconds_including_children` |
| archive_content_aborted001 | process_self_cpu_through_receipt | 35.146398380 | `experiments/hcsn_distributional_v2/artifacts/content_aborted001_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| archive_execution_v2_001 | process_self_cpu_through_receipt | 2.843813874 | `experiments/hcsn_distributional_v2/artifacts/execution_v2_001_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| archive_lif_supplement001_evidence | complete_process_tree_wait4 | 47.513060000 | `experiments/hcsn_distributional_v2/results/evidence_sealing/lif_supplement001_evidence/EXECUTION.json#/complete_archive_child_cpu_seconds` |
| archive_task_value_and_control002 | process_self_cpu_through_receipt | 32.293515660 | `experiments/hcsn_distributional_v2/artifacts/task_value_and_control002_EXECUTION.json#/whole_process_self_cpu_seconds_through_seal` |
| archive_v2_auxiliary_evidence | complete_process_tree_wait4 | 9.461997000 | `experiments/hcsn_distributional_v2/results/evidence_sealing/v2_auxiliary_evidence/EXECUTION.json#/complete_archive_child_cpu_seconds` |
| archive_coordinator_content002_metadata | process_self_cpu_through_receipt | 0.083011094 | `experiments/hcsn_distributional_v2/results/evidence_sealing/content002_metadata/EXECUTION.json#/coordinator_whole_self_cpu_seconds_through_cutoff` |
| archive_coordinator_lif_supplement001_evidence | process_self_cpu_through_receipt | 0.533595075 | `experiments/hcsn_distributional_v2/results/evidence_sealing/lif_supplement001_evidence/EXECUTION.json#/coordinator_whole_self_cpu_seconds_through_cutoff` |
| archive_coordinator_v2_auxiliary_evidence | process_self_cpu_through_receipt | 1.936783385 | `experiments/hcsn_distributional_v2/results/evidence_sealing/v2_auxiliary_evidence/EXECUTION.json#/coordinator_whole_self_cpu_seconds_through_cutoff` |
| archive_watcher_20261030T022409Z_c7d04be3_EXECUTION | process_self_cpu_through_receipt | 15.851976416 | `experiments/hcsn_distributional_v2/results/content_checkpoint_archives/instances/20261030T022409Z_c7d04be3_EXECUTION.json#/own_cpu_seconds` |
| scaling002_suite | complete_process_tree_wait4 | 99.448615000 | `experiments/hcsn_distributional_v2/results/scaling002/SUITE_EXECUTION.json#/complete_child_cpu_seconds` |
| scaling002_supervisor | process_self_cpu_through_receipt | 0.260789747 | `experiments/hcsn_distributional_v2/results/scaling002/SUITE_EXECUTION.json#/supervisor_self_cpu_seconds_through_cutoff` |
| scaling002_summary_repair | complete_process_tree_wait4 | 0.233307000 | `experiments/hcsn_distributional_v2/results/scaling002_summary_repair001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling002_summary_repair_supervisor | process_self_cpu_through_receipt | 0.037437467 | `experiments/hcsn_distributional_v2/results/scaling002_summary_repair001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
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
| campaign_costs_probe003_child | complete_process_tree_wait4 | 0.137960000 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe003/WRAPPER_EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_probe003_parent | process_self_cpu_through_receipt | 0.031040870 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe003/WRAPPER_EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| sealing_smoke001_child | complete_process_tree_wait4 | 0.548682000 | `experiments/hcsn_distributional_v2/results/sealing_smoke001/EXECUTION.json#/cpu_seconds_including_children` |
| sealing_smoke001_parent | process_self_cpu_through_receipt | 0.054127003 | `experiments/hcsn_distributional_v2/results/sealing_smoke001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| archive_closure_tests001_child | complete_process_tree_wait4 | 5.001471000 | `experiments/hcsn_distributional_v2/results/archive_closure_tests001/EXECUTION.json#/cpu_seconds_including_children` |
| archive_closure_tests001_parent | process_self_cpu_through_receipt | 0.040403648 | `experiments/hcsn_distributional_v2/results/archive_closure_tests001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| archive_closure_scaling_interface002_child | complete_process_tree_wait4 | 0.145553000 | `experiments/hcsn_distributional_v2/results/archive_closure_scaling_interface002/EXECUTION.json#/cpu_seconds_including_children` |
| archive_closure_scaling_interface002_parent | process_self_cpu_through_receipt | 0.026018660 | `experiments/hcsn_distributional_v2/results/archive_closure_scaling_interface002/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| lif_scheduler_supervisor_window | partial_process_body_timer | 0.002678172 | `experiments/hcsn_distributional_v2/results/lif_supplement001/SCHEDULER_EXECUTION.json#/outer_supervisor_self_window_cpu_seconds` |
| scaling_preflight_child | complete_process_tree_wait4 | 5.715105000 | `experiments/hcsn_distributional_v2/results/scaling_preflight001/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling_prepare_parent | process_self_cpu_through_receipt | 0.096268076 | `experiments/hcsn_distributional_v2/results/scaling_preflight001/PREPARE_EXECUTION.json#/coordinator_whole_self_cpu_seconds_through_cutoff` |
| cost_lif_exit_regression_child | complete_process_tree_wait4 | 0.087294000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests004/EXECUTION.json#/complete_child_cpu_seconds` |
| cost_lif_exit_regression_parent | process_self_cpu_through_receipt | 0.045510387 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests004/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| cost_scaling_containment_regression_child | complete_process_tree_wait4 | 0.236159000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests005/EXECUTION.json#/complete_child_cpu_seconds` |
| cost_scaling_containment_regression_parent | process_self_cpu_through_receipt | 0.069763097 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests005/EXECUTION.json#/outer_parent_self_cpu_seconds_to_cutoff` |
| archive_closure_gate_tests003_child | complete_process_tree_wait4 | 0.570337000 | `experiments/hcsn_distributional_v2/results/archive_closure_gate_tests003/EXECUTION.json#/cpu_seconds_including_children` |
| archive_closure_gate_tests003_supervisor | process_self_cpu_through_receipt | 0.065003328 | `experiments/hcsn_distributional_v2/results/archive_closure_gate_tests003/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| final_report_guard_tests001_child | complete_process_tree_wait4 | 0.389068000 | `experiments/hcsn_distributional_v2/results/final_report_guard_tests001/EXECUTION.json#/complete_child_cpu_seconds` |
| final_report_guard_tests001_supervisor | process_self_cpu_through_receipt | 0.043472537 | `experiments/hcsn_distributional_v2/results/final_report_guard_tests001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| final_bundle_plan_tests001_child | complete_process_tree_wait4 | 0.236142000 | `experiments/hcsn_distributional_v2/results/final_bundle_plan_tests001/EXECUTION.json#/cpu_seconds_including_children` |
| final_bundle_plan_tests001_supervisor | process_self_cpu_through_receipt | 0.095849755 | `experiments/hcsn_distributional_v2/results/final_bundle_plan_tests001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| content_ce_diagnostic001_child | complete_process_tree_wait4 | 4.183710000 | `experiments/hcsn_distributional_v2/results/content_ce_diagnostic001_measurement/EXECUTION.json#/complete_child_cpu_seconds` |
| content_ce_diagnostic001_supervisor | process_self_cpu_through_receipt | 0.053508946 | `experiments/hcsn_distributional_v2/results/content_ce_diagnostic001_measurement/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| content_ce_diagnostic002_child | complete_process_tree_wait4 | 4.320447000 | `experiments/hcsn_distributional_v2/results/content_ce_diagnostic002_measurement/EXECUTION.json#/complete_child_cpu_seconds` |
| content_ce_diagnostic002_supervisor | process_self_cpu_through_receipt | 0.093122362 | `experiments/hcsn_distributional_v2/results/content_ce_diagnostic002_measurement/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| content_supplement_preflight001_child | complete_process_tree_wait4 | 3.087537000 | `experiments/hcsn_distributional_v2/results/content_supplement_preflight001/EXECUTION.json#/complete_child_cpu_seconds` |
| content_supplement_preflight001_supervisor | process_self_cpu_through_receipt | 0.044730328 | `experiments/hcsn_distributional_v2/results/content_supplement_preflight001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| admission_consumer004_snapshot_child | complete_process_tree_wait4 | 0.034932000 | `experiments/hcsn_distributional_v2/results/admission_consumer004_snapshot_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| admission_consumer004_snapshot_supervisor | process_self_cpu_through_receipt | 0.039641978 | `experiments/hcsn_distributional_v2/results/admission_consumer004_snapshot_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| admission_consumer004_validation_child | complete_process_tree_wait4 | 0.209324000 | `experiments/hcsn_distributional_v2/results/admission_consumer004_validation_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| admission_consumer004_validation_supervisor | process_self_cpu_through_receipt | 0.040991250 | `experiments/hcsn_distributional_v2/results/admission_consumer004_validation_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| lif_cost_normalization001_child | complete_process_tree_wait4 | 0.154924000 | `experiments/hcsn_distributional_v2/results/lif_cost_normalization001/EXECUTION.json#/complete_child_cpu_seconds` |
| lif_cost_normalization001_supervisor | process_self_cpu_through_receipt | 0.043511073 | `experiments/hcsn_distributional_v2/results/lif_cost_normalization001/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| scaling002_admission_tests001_child | complete_process_tree_wait4 | 0.525930000 | `experiments/hcsn_distributional_v2/results/scaling002_admission_tests001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling002_admission_tests001_supervisor | process_self_cpu_through_receipt | 0.048711392 | `experiments/hcsn_distributional_v2/results/scaling002_admission_tests001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| scaling002_admission_tests002_child | complete_process_tree_wait4 | 0.422611000 | `experiments/hcsn_distributional_v2/results/scaling002_admission_tests002_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling002_admission_tests002_supervisor | process_self_cpu_through_receipt | 0.046008585 | `experiments/hcsn_distributional_v2/results/scaling002_admission_tests002_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| scaling002_registration001_child | complete_process_tree_wait4 | 0.102490000 | `experiments/hcsn_distributional_v2/results/scaling002_registration001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling002_registration001_supervisor | process_self_cpu_through_receipt | 0.036110991 | `experiments/hcsn_distributional_v2/results/scaling002_registration001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| campaign_costs_tests006_child | complete_process_tree_wait4 | 0.073693000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests006/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_tests006_supervisor | process_self_cpu_through_receipt | 0.038835201 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests006/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| campaign_costs_tests007_child | complete_process_tree_wait4 | 0.100010000 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests007/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_tests007_supervisor | process_self_cpu_through_receipt | 0.039350156 | `experiments/hcsn_distributional_v2/results/campaign_costs_tests007/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| campaign_costs_probe004_child | complete_process_tree_wait4 | 0.136878000 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe004_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_probe004_supervisor | process_self_cpu_through_receipt | 0.047502993 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe004_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| campaign_costs_probe005_child | complete_process_tree_wait4 | 0.145490000 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe005_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| campaign_costs_probe005_supervisor | process_self_cpu_through_receipt | 0.033412701 | `experiments/hcsn_distributional_v2/results/campaign_costs_probe005_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| figures002_child | complete_process_tree_wait4 | 4.265244000 | `experiments/hcsn_distributional_v2/results/figures002_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| figures002_supervisor | process_self_cpu_through_receipt | 0.035959894 | `experiments/hcsn_distributional_v2/results/figures002_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| scaling_summary_consumer005_snapshot_child | complete_process_tree_wait4 | 0.032933000 | `experiments/hcsn_distributional_v2/results/scaling_summary_consumer005_snapshot_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling_summary_consumer005_snapshot_supervisor | process_self_cpu_through_receipt | 0.036817044 | `experiments/hcsn_distributional_v2/results/scaling_summary_consumer005_snapshot_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| scaling_summary_consumer005_validation_child | complete_process_tree_wait4 | 0.331292000 | `experiments/hcsn_distributional_v2/results/scaling_summary_consumer005_validation_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| scaling_summary_consumer005_validation_supervisor | process_self_cpu_through_receipt | 0.042012093 | `experiments/hcsn_distributional_v2/results/scaling_summary_consumer005_validation_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| archive_closure001_child | complete_process_tree_wait4 | 2.955558000 | `experiments/hcsn_distributional_v2/results/archive_closure001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| archive_closure001_supervisor | process_self_cpu_through_receipt | 0.037574526 | `experiments/hcsn_distributional_v2/results/archive_closure001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| final_catalog001_child | complete_process_tree_wait4 | 0.714829000 | `experiments/hcsn_distributional_v2/reproduction_receipts/final_catalog001_execution/EXECUTION.json#/complete_child_cpu_seconds` |
| final_catalog001_supervisor | process_self_cpu_through_receipt | 0.034920927 | `experiments/hcsn_distributional_v2/reproduction_receipts/final_catalog001_execution/EXECUTION.json#/supervisor_self_cpu_seconds_through_receipt` |
| final_bundle_plan_lif_supplement001_evidence | process_self_cpu_through_receipt | 1.827465080 | `experiments/hcsn_distributional_v2/results/final_bundle_plans/lif_supplement001_evidence_001/EXECUTION.json#/own_cpu_seconds_through_receipt` |
| final_bundle_plan_content002_metadata | process_self_cpu_through_receipt | 2.171250009 | `experiments/hcsn_distributional_v2/results/final_bundle_plans/content002_metadata_001/EXECUTION.json#/own_cpu_seconds_through_receipt` |
| final_bundle_plan_v2_auxiliary_evidence | process_self_cpu_through_receipt | 3.098995588 | `experiments/hcsn_distributional_v2/results/final_bundle_plans/v2_auxiliary_evidence_001/EXECUTION.json#/own_cpu_seconds_through_receipt` |

Full receipt SHA-256 bindings, original component reconciliations, scope exclusions and missing inputs are in LEDGER.json. Aggregate components are validation evidence and are never added a second time.

## Missing required inputs

None within the declared receipt scope.

## Unknown and excluded work

- Remote restoration/download and environment installation CPU were not fully receipted; remote wall time is not converted to CPU.
- Untimed development, source inspection/editing, early numerical smoke, compilation, and partial timer remainders are unknown.
- Supervisor/import/serialization/exit work outside recorded windows or self-CPU cutoffs is unknown.
- Failed task001's early supervisor snapshot is not added without a proven independent process scope; the full failed child tree is charged.
- Publishing, later archive/report updates, this ledger generation and all work after the stated cutoff are outside this lower bound.

The ledger generator records its own self CPU separately in EXECUTION.json after this ledger cutoff. This avoids self-referential cost totals. Earlier probes or extra reports enter a later ledger only through an explicit additional-scope declaration.
