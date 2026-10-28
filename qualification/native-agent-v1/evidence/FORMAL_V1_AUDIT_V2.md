# Formal resident-lane summary — audit v2

Audit v2 preserves the gateway's JSON insertion order; v1 incorrectly sorted keys. The original reports, captures and v1 failed audit are retained.

Memory is sampled complete-scope PSS; CPU columns overlap and must not be added.

| Mode / lane | Correct / planned (attempted; correctness unknown) | Warmup correct / planned (unknown) | Measured completed rows median / p95 ms (known / completed n) | Completed incorrect | Startup / shutdown ms | PSS MiB (complete / incomplete samples) | Cgroup CPU s | Process CPU s | Live measured input / output / total tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| live / app-server | 6 / 6 (6; 0) | 1 / 1 (0) | 7736.02 / 8770.00 (6 / 6) | 0 | 265.79 / 175.43 | 232.18 (639 / 38) | 64.65 | 63.73 | 29876 / 715 / 30591 |
| live / facade | 6 / 6 (6; 0) | 1 / 1 (0) | 7625.68 / 8723.64 (6 / 6) | 0 | 785.28 / 390.01 | 202.94 (651 / 37) | 66.35 | 65.35 | 29570 / 757 / 30327 |
| live / native | 6 / 6 (6; 0) | 1 / 1 (0) | 5549.27 / 6451.69 (6 / 6) | 0 | 6.31 / 221.86 | 40.98 (507 / 34) | 45.16 | 44.49 | 16986 / 703 / 17689 |
| replay / app-server | 9 / 9 (9; 0) | 1 / 1 (0) | 2375.05 / 2836.57 (9 / 9) | 0 | 246.60 / 458.13 | 236.81 (217 / 53) | 35.05 | 33.71 | synthetic replay; not actual consumption |
| replay / facade | 9 / 9 (9; 0) | 1 / 1 (0) | 2346.09 / 2418.03 (9 / 9) | 0 | 193.30 / 465.42 | 209.46 (227 / 46) | 34.29 | 32.80 | synthetic replay; not actual consumption |
| replay / native | 9 / 9 (9; 0) | 1 / 1 (0) | 2142.71 / 4616.27 (9 / 9) | 0 | 6.31 / 508.97 | 40.85 (292 / 46) | 33.77 | 32.89 | synthetic replay; not actual consumption |

## Gates and coverage

### live / app-server

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.14277854398824275, "observer_cpu_seconds": 52.92891973200004, "observer_pid": 699573, "observer_wall_seconds": 53.33496377320262, "samples": 677, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.881694008163188, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8749815896509895, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b291ee-96a-2bd6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b2d1f9-aad8f-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b2ecfa-aad8f-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b30e09-aad8f-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b32901-aad8f-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b34d59-aad8f-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b36845-aad8f-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b38208-aad8f-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 8, "pss_missing:ProcessLookupError": 5, "selected_pid_stat_missing": 37}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 44, "process_identities_observed": 46, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [699573]}`
- Issues: `[]`

### live / facade

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.13220172299770638, "observer_cpu_seconds": 55.08407591000002, "observer_pid": 693060, "observer_wall_seconds": 55.48157247211202, "samples": 688, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.8842016833897818, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8778668389774726, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b0da13-96a-2bc8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b11767-a938e-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b13551-a938e-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b1530a-a938e-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b170f3-a938e-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b19083-a938e-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b1ab08-a938e-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b1c786-a938e-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 4, "pss_missing:ProcessLookupError": 3, "selected_pid_stat_missing": 36}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 44, "process_identities_observed": 46, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [693060]}`
- Issues: `[]`

### live / native

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": true}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.12571889298851602, "observer_cpu_seconds": 38.64520181200002, "observer_pid": 707067, "observer_wall_seconds": 38.712402510573156, "samples": 541, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.872140517808208, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8706265727092274, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b4e9af-96a-2be3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b50190-aca09-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b517b2-aca09-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b52c3f-aca09-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b5412e-aca09-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b55cab-aca09-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b570f9-aca09-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b58652-aca09-7.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted", "Upstream model service process tree and compute are not measured"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 4, "pss_missing:ProcessLookupError": 3, "selected_pid_stat_missing": 30}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 35, "process_identities_observed": 37, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [707067]}`
- Issues: `[]`

### replay / app-server

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.14157962100580335, "observer_cpu_seconds": 22.034521741999995, "observer_pid": 682180, "observer_wall_seconds": 22.23680479673203, "samples": 270, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.886674708938089, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8786088348020713, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae5c02-96a-2bb3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae73c9-a694b-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae7cfa-a694b-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae8645-a694b-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae8f3e-a694b-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ae98d3-a694b-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aea240-a694b-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aeab33-a694b-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aeb47f-a694b-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aebdce-a694b-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aec6d4-a694b-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 13, "pss_missing:ProcessLookupError": 1, "selected_pid_stat_missing": 50}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 52, "process_identities_observed": 58, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [682180]}`
- Issues: `[]`

### replay / facade

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": "unknown"}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.13274220598395914, "observer_cpu_seconds": 21.419665993000017, "observer_pid": 687818, "observer_wall_seconds": 21.603930205194047, "samples": 273, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.8825767645537562, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8750490920110003, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afb1fc-96a-2bbb.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afc4b0-a7fd7-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afcdeb-a7fd7-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afd712-a7fd7-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afe04e-a7fd7-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180afe968-a7fd7-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aff29b-a7fd7-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180affbbb-a7fd7-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b00503-a7fd7-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b00e47-a7fd7-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180b0176c-a7fd7-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 13, "pss_missing:ProcessLookupError": 1, "selected_pid_stat_missing": 37}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 54, "process_identities_observed": 60, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [687818]}`
- Issues: `[]`

### replay / native

- Gates: `{"actual_only_shared_tool_inventory": true, "advertised_model_matches": true, "captured_model_call_budget": true, "completed_output_tokens_within_256": true, "effective_cap_verified_within_256": true, "effective_request_bytes_verified_within_65536": true, "executor_tool_call_budget": true, "formal_plan_matches": true, "full_capture_budget_evidence_verified": true, "generated_tool_call_budget": true, "model_capture_complete": true, "only_shared_tool_inventory": true, "recorded_model_call_budget": true, "reported_completed_lane": true, "reported_equal_tool_comparison": true, "reported_qualification_passed": true, "reported_success_and_full_plan_verified": true, "request_bytes_within_65536": true, "requested_cap_within_256": true}`
- Sampling: `{"interval_seconds": 0.01, "largest_actual_gap_seconds": 0.10316466400399804, "observer_cpu_seconds": 24.799071156000014, "observer_pid": 674977, "observer_wall_seconds": 24.854582920961548, "samples": 338, "stop_timeout": false}`
- Sampling interpretation: `{"active_wall_over_lane_elapsed": 0.8752493394872883, "cpu_clock": "sum of per-_sample calling-thread time.thread_time deltas; includes synchronous start/stop samples", "cpu_over_lane_elapsed": 0.8732945034004845, "subtracting_sampler_cpu_recovers_uninstrumented_executor_cost": false, "wall_clock": "sum of active _sample time.monotonic deltas; excludes inter-sample event.wait intervals"}`
- Coverage: `{"cgroup_paths_requested": ["/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180aceb15-96a-2ba8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180acef2b-a4cbe-1.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180acf777-a4cbe-2.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180acff8d-a4cbe-3.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad080c-a4cbe-4.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad1035-a4cbe-5.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad1846-a4cbe-6.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad2449-a4cbe-7.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad35fa-a4cbe-8.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad4453-a4cbe-9.service", "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-1a180ad5315-a4cbe-a.service"], "explicit_pid_scope_pinned_to_first_start_ticks": true, "external_work_declared": ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"], "extra_pids_requested": [], "gaps": {"pid_disappeared_during_sample": 3, "pss_missing:ProcessLookupError": 4, "selected_pid_stat_missing": 42}, "global_total_memory_or_cpu_claim_supported": false, "observer_process_included": true, "polling_can_miss_short_lived_processes": true, "process_exit_endpoints_missing": 52, "process_identities_observed": 54, "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.", "root_pids_requested": [674977]}`
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
      "started_ns": 1793160179387416419,
      "finished_ns": 1793160207716972553,
      "mode": "replay",
      "lane": "native"
    },
    {
      "started_ns": 1793160278451667867,
      "finished_ns": 1793160303470588222,
      "mode": "replay",
      "lane": "app-server"
    },
    {
      "started_ns": 1793160364813188498,
      "finished_ns": 1793160389231017115,
      "mode": "replay",
      "lane": "facade"
    },
    {
      "started_ns": 1793160440543356770,
      "finished_ns": 1793160503223809198,
      "mode": "live",
      "lane": "facade"
    },
    {
      "started_ns": 1793160555106500854,
      "finished_ns": 1793160615570917953,
      "mode": "live",
      "lane": "app-server"
    },
    {
      "started_ns": 1793160703317808428,
      "finished_ns": 1793160747638143135,
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
