# Formal resident-lane summary — audit v2

Audit v2 preserves the gateway's JSON insertion order; v1 incorrectly sorted keys. The original reports, captures and v1 failed audit are retained.

Memory is sampled complete-scope PSS; CPU columns overlap and must not be added.

| Mode / lane | Correct / planned (attempted; correctness unknown) | Warmup correct / planned (unknown) | Measured completed rows median / p95 ms (known / completed n) | Completed incorrect | Startup / shutdown ms | PSS MiB (complete / incomplete samples) | Cgroup CPU s | Process CPU s | Live measured input / output / total tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| live / app-server | 6 / 6 (6; 0) | 1 / 1 (0) | 9336.59 / 11753.66 (6 / 6) | 0 | 249.08 / 163.89 | 228.65 (147 / 2) | 13.12 | 10.92 | 29820 / 975 / 30795 |
| live / facade | 6 / 6 (6; 0) | 1 / 1 (0) | 7310.97 / 9717.25 (6 / 6) | 0 | 211.81 / 497.31 | 204.71 (112 / 2) | 11.58 | 8.90 | 30158 / 801 / 30959 |
| live / native | 6 / 6 (6; 0) | 1 / 1 (0) | 6251.52 / 7363.07 (6 / 6) | 0 | 5.03 / 325.02 | 40.05 (93 / 1) | 6.92 | 5.34 | 16986 / 780 / 17766 |
| replay / app-server | 9 / 9 (9; 0) | 1 / 1 (0) | 2355.96 / 2621.41 (9 / 9) | 0 | 590.61 / 472.39 | 234.54 (46 / 4) | 12.97 | 10.29 | synthetic replay; not actual consumption |
| replay / facade | 9 / 9 (9; 0) | 1 / 1 (0) | 2313.78 / 2614.06 (9 / 9) | 0 | 223.31 / 479.49 | 212.40 (48 / 0) | 12.60 | 9.75 | synthetic replay; not actual consumption |
| replay / native | 9 / 9 (9; 0) | 1 / 1 (0) | 2101.29 / 2182.21 (9 / 9) | 0 | 5.69 / 495.25 | 39.45 (42 / 2) | 8.55 | 6.81 | synthetic replay; not actual consumption |

## Gates and coverage

### live / app-server

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5354365219827741, "observer_cpu_seconds": 2.5217022, "observer_pid": 837030, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.33389537000000025, "pid_enumeration": 0.8867595200000008, "pss_and_aggregation": 1.3004227100000003}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.3346230319002643, "pid_enumeration": 0.8926651731017046, "pss_and_aggregation": 1.301331577997189}, "observer_wall_seconds": 2.529547612735769, "samples": 149, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.033158082709065416, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.03305524264269559, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180db3445-96a-2ccd.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180db6e5c-cc69f-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dbaba3-cc69f-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dbcc23-cc69f-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dbf473-cc69f-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dc1871-cc69f-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dc3584-cc69f-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dc60d6-cc69f-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 1, "pss_missing:ProcessLookupError": 1, "task_disappeared_during_enumeration": 1}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 155, "cgroup_scopes_read": 620, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 1746, "scoped_samples": 149, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 7318}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 40, "process_identities_observed": 42, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [837030]}`
- Issues: `[]`

### live / facade

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5326526650169399, "observer_cpu_seconds": 2.038276980999999, "observer_pid": 828102, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.2887113779999986, "pid_enumeration": 0.721888953000001, "pss_and_aggregation": 1.0271381250000005}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.2892310061433818, "pid_enumeration": 0.7266138149716426, "pss_and_aggregation": 1.0282646432169713}, "observer_wall_seconds": 2.044905689981533, "samples": 114, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.03503691475231374, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.03492334007127014, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d90ef3-96a-2cc2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d9445d-ca329-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d96026-ca329-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d97706-ca329-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d991cb-ca329-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d9b541-ca329-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d9d765-ca329-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d9efb4-ca329-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 1, "pss_missing:ProcessLookupError": 1}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 119, "cgroup_scopes_read": 492, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 1462, "scoped_samples": 114, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 5155}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 39, "process_identities_observed": 41, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [828102]}`
- Issues: `[]`

### live / native

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": true}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5118728099914733, "observer_cpu_seconds": 0.7899044469999998, "observer_pid": 848923, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.235742465, "pid_enumeration": 0.22048431899999982, "pss_and_aggregation": 0.33325119500000017}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.23622461600461975, "pid_enumeration": 0.22192134489887394, "pss_and_aggregation": 0.33341247896896675}, "observer_wall_seconds": 0.792200650961604, "samples": 94, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.016883393510644874, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.016834456773446534, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180deb21a-96a-2cd9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180dec026-cf42c-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ded9f7-cf42c-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180def9e6-cf42c-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180df0e6c-cf42c-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180df26fb-cf42c-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180df4158-cf42c-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180df5adf-cf42c-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pss_missing:ProcessLookupError": 1}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 98, "cgroup_scopes_read": 439, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 626, "scoped_samples": 94, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 1371}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 30, "process_identities_observed": 32, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [848923]}`
- Issues: `[]`

### replay / app-server

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5366696850105654, "observer_cpu_seconds": 1.0097734260000002, "observer_pid": 812911, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.1500886240000009, "pid_enumeration": 0.3403899820000006, "pss_and_aggregation": 0.5190596269999985}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.15199978300370276, "pid_enumeration": 0.3433263959013857, "pss_and_aggregation": 0.521915201068623}, "observer_wall_seconds": 1.0175896871369332, "samples": 50, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.04025832040843347, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.03994909012708895, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5a2e3-96a-2cb0.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5bd7e-c6876-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5c741-c6876-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5d1ac-c6876-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5dac4-c6876-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5e4e4-c6876-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5ee22-c6876-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d5f764-c6876-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d60076-c6876-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d609b0-c6876-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d612a0-c6876-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_enumeration": 1, "pid_disappeared_during_sample": 2, "pss_missing:ProcessLookupError": 1, "selected_pid_stat_missing": 1, "task_disappeared_during_enumeration": 1}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 52, "cgroup_scopes_read": 314, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 801, "scoped_samples": 50, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 2442}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 41, "process_identities_observed": 47, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [812911]}`
- Issues: `[]`

### replay / facade

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5341744399920572, "observer_cpu_seconds": 0.9730793660000002, "observer_pid": 820388, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.1527655869999998, "pid_enumeration": 0.32734991800000074, "pss_and_aggregation": 0.4927414450000001}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.15354254108387977, "pid_enumeration": 0.32827400087262504, "pss_and_aggregation": 0.49509034494985826}, "observer_wall_seconds": 0.9772338059847243, "samples": 48, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.04036101035425709, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.040189426651142536, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7747e-96a-2cb5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d787bd-c85a9-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d790c4-c85a9-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d799d4-c85a9-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7a2d4-c85a9-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7ac1c-c85a9-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7b65b-c85a9-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7bf8c-c85a9-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7c874-c85a9-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7d174-c85a9-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d7da7d-c85a9-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 52, "cgroup_scopes_read": 311, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 814, "scoped_samples": 48, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 2200}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 49, "process_identities_observed": 55, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [820388]}`
- Issues: `[]`

### replay / native

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": true}`
- Sampling: `{"cadence": "wait_after_sample", "implementation": "hepta.process-metrics.linux.v2", "interval_seconds": 0.5, "largest_actual_gap_seconds": 0.5150117010052782, "observer_cpu_seconds": 0.42686383899999997, "observer_pid": 806248, "observer_stage_cpu_seconds": {"cgroup_discovery": 0.14012813799999999, "pid_enumeration": 0.11391914100000003, "pss_and_aggregation": 0.17260982300000005}, "observer_stage_wall_seconds": {"cgroup_discovery": 0.14048092984012328, "pid_enumeration": 0.11539895602618344, "pss_and_aggregation": 0.1726354390848428}, "observer_wall_seconds": 0.42880065090139396, "samples": 44, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.01981487555580266, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.019725375489232224, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d48b9d-96a-2ca8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d48f86-c4d7a-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d497ee-c4d7a-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4a018-c4d7a-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4a841-c4d7a-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4b053-c4d7a-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4b88b-c4d7a-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4c0e1-c4d7a-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4c955-c4d7a-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4d1b2-c4d7a-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180d4d9c9-c4d7a-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_enumeration": 1, "pid_disappeared_during_sample": 1, "selected_pid_stat_missing": 1}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "pid_enumeration": {"cgroup_procs_read_attempts": 46, "cgroup_scopes_read": 290, "fallback": "full_proc_scan_on_permission_or_capability_failure", "normal_exits_are_recorded_without_global_fallback": true, "proc_stat_read_attempts": 339, "scoped_samples": 44, "strategy": "explicit_cgroups_and_all_selected_task_children", "task_children_read_attempts": 668}, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 40, "process_identities_observed": 42, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [806248]}`
- Issues: `[]`

## Comparison checks

```json
{
  "six_unique_formal_lanes_present": true,
  "missing_lanes": [],
  "duplicate_lanes": [],
  "same_helper_binary": true,
  "same_fixture_script": true,
  "same_fixture_data": true,
  "same_budget_ceilings": true,
  "same_case_timeout": true,
  "same_advertised_model": true,
  "same_provider_weights": "unknown",
  "same_source_and_compiler_requires_external_manifest": "unknown",
  "same_executor_across_modes": {
    "app-server": true,
    "facade": true,
    "native": true
  },
  "same_case_order_per_mode": {
    "replay": true,
    "live": true
  },
  "model_visible_options_require_inventory_review": true,
  "resource_cap_checks": {
    "cpu.max": true,
    "cpu.weight": true,
    "memory.max": true,
    "cpuset.cpus.effective": "unknown",
    "affinity_cpus": true
  },
  "run_order": [
    {
      "started_ns": 1793162776342514230,
      "finished_ns": 1793162797996287392,
      "mode": "replay",
      "lane": "native"
    },
    {
      "started_ns": 1793162852946467584,
      "finished_ns": 1793162878244571274,
      "mode": "replay",
      "lane": "app-server"
    },
    {
      "started_ns": 1793162970616328238,
      "finished_ns": 1793162994847814549,
      "mode": "replay",
      "lane": "facade"
    },
    {
      "started_ns": 1793163075477672751,
      "finished_ns": 1793163133862230944,
      "mode": "live",
      "lane": "facade"
    },
    {
      "started_ns": 1793163217559523728,
      "finished_ns": 1793163293869671310,
      "mode": "live",
      "lane": "app-server"
    },
    {
      "started_ns": 1793163441909325981,
      "finished_ns": 1793163488839472760,
      "mode": "live",
      "lane": "native"
    }
  ]
}
```

## Limits

- Whole-lane CPU/memory includes startup, warmup, observer and shutdown; it is not steady-state per-case cost.
- PSS completeness describes observed selected scopes, not global coverage; sampled peaks are lower bounds.
- Cgroup memory.peak is cumulative lifetime high-water and is deliberately excluded.
- Process CPU, cgroup CPU, waited-child CPU and observer CPU overlap; they must not be added.
- Observer CPU is active sampling-call thread_time, not total observer-process CPU; active sampling wall excludes interval waits.
- Sampler CPU subtraction cannot reconstruct uninstrumented executor cost, latency, memory, GIL, scheduling, I/O or cache effects.
- Live upstream model compute/memory and some loopback SSH/control-plane work are outside measured scopes.
- Replay usage is synthetic and must not be presented as actual token consumption.
- Small sequential samples, caches and changing host/provider load do not establish stable superiority.
- No normal benchmark result proves original-operation recovery; that needs separate fault evidence.
- Captured model-call counts cover admitted requests; attempts rejected before gateway recording are not an exhaustive HTTP attempt log.
