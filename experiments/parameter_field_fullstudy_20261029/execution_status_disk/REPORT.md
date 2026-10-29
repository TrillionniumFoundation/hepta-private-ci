# Parameter-field / Hepta full-study results

Status: **BLOCKED**.

The original 1 GiB storage / 2 GiB reserve contract did not pass. Operational amendments and failed attempts remain part of the record.

No unfinished scientific endpoint outcomes were opened. Planned work is separate from executed work.

```json
{
  "incomplete_stages": {
    "A": "BLOCKED",
    "B": "PENDING",
    "C": "BLOCKED",
    "W": "PENDING",
    "R": "PENDING"
  },
  "planned_gradient_microsteps": {
    "A": 117504,
    "B": 69120,
    "C": 57536,
    "W": 2880,
    "R": 96768
  },
  "resource_status": {
    "status": "ADMISSION_BLOCKED",
    "at_utc": "2026-10-29T11:47:45.087426+00:00",
    "memory": {
      "current": 8158932992,
      "limit": 8589934592,
      "inactive_file": 673386496,
      "file_dirty": 22953984,
      "file_writeback": 0,
      "clean_inactive_file": 650432512,
      "effective_current": 7508500480,
      "oom": 8,
      "oom_kill": 4,
      "required_headroom": 1879048192,
      "allowed": false
    },
    "source_registration_scope": "LOCAL_ONLY_NOT_PUBLISHED",
    "amendment_sha256": "d0572d7c26f7d15f9a78f3a8d6e6b72f70ae709e075c89a04f4599d90146d372",
    "controller_freeze_sha256": "91f1cf6dee69f7240a3c4cd9ba223facc7003cd96d0d95413f53a89a09a30e14",
    "actual_recovery_exit_code": 75,
    "recovery_archived": false,
    "scientific_workers_started": 0,
    "gradient_microsteps": 0,
    "new_endpoint_roles_opened": [],
    "publication_status": "BLOCKED_AUTO_REVIEW_PUBLIC_DISCLOSURE",
    "shared_cache_cleanup_status": "AWAITING_SPECIFIC_CROSS_WORKFLOW_AUTHORIZATION",
    "actual_check_receipt": {
      "path": "/dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/evidence/ENVELOPE_RECOVERY_CHECK_20261029.json",
      "bytes": 1756,
      "sha256": "70f4d4db545327480365b0826ab007c6c9a95e8dbea31aefeaaa7d3c88b349aa"
    },
    "zero_science_controller_failure": {
      "receipt": {
        "path": "/dev/shm/hepta-field-fullstudy-20261029/source/experiments/parameter_field_fullstudy_20261029/evidence/CONTROLLER_FAILURE_20261029.json",
        "bytes": 3930,
        "sha256": "623b64d0c599cf5705e198bcbb387138a5b9901aef37d1106201c6218d62f57e"
      },
      "training_microsteps_lower_bound": 0,
      "engineering_microsteps_included": 0,
      "unknown_additional_work": false,
      "scope": "attempt02 pre-science controller progress-write memory failure; operational CPU/wall work is separate, not zero total resource cost"
    },
    "report_input_correction": {
      "previous_invalid_input_sha256": "0cf7075dd5bd65ce1ec9ab4109a26da12f9d30d2e886027bfe947e39f9d371dd",
      "reason": "The frozen failed_attempts cost schema only accepts training failures with unknown additional work. The known-zero-science controller failure is operational evidence and is carried under resource_status instead; no cost, original failure or scientific criterion is changed."
    }
  },
  "prior_attempt_costs": {
    "engineering_receipts": [
      {
        "kind": "engineering_preflight",
        "receipt_sha256": "996243b3a03cc3aca9fc9b57593029c6702e30c8762b6085e22d47d90e43fa59",
        "gradient_microsteps": 432,
        "ledger": {
          "original_guard_generator_calls": 2,
          "original_guard_generator_examples": 256,
          "original_guard_generator_refinement_examples": 256,
          "original_guard_reward_observer_calls": 4,
          "original_guard_reward_observer_digit_examples": 512,
          "cold_cache_initialization_generator_calls": 1,
          "cold_cache_initialization_generator_examples": 128,
          "cold_cache_initialization_generator_refinement_examples": 128,
          "cold_cache_initialization_reward_observer_calls": 2,
          "cold_cache_initialization_reward_observer_digit_examples": 256,
          "state_capture_wall_ns": 653456553,
          "state_capture_cpu_ns": 694508354,
          "state_serialize_wall_ns": 70532449,
          "state_serialize_cpu_ns": 70535035,
          "serialized_branch_bytes": 3172930,
          "complete_branch_restores": 10,
          "state_restore_wall_ns": 2369868932,
          "state_restore_cpu_ns": 2367539626,
          "transaction_snapshots": 9,
          "gradient_generator_calls": 864,
          "gradient_generator_examples": 41472,
          "gradient_generator_refinement_examples": 41472,
          "gradient_teacher_calls": 864,
          "gradient_teacher_examples": 41472,
          "gradient_teacher_refinement_examples": 41472,
          "gradient_backward_calls": 432,
          "gradient_backward_examples": 41472,
          "optimizer_steps": 336,
          "scheduled_gradient_microsteps": 432,
          "candidate_guard_generator_calls": 18,
          "candidate_guard_generator_examples": 2304,
          "candidate_guard_generator_refinement_examples": 2304,
          "candidate_guard_reward_observer_calls": 36,
          "candidate_guard_reward_observer_digit_examples": 4608,
          "rejected_blocks": 3,
          "discarded_gradient_microsteps": 144,
          "guarded_transition_wall_ns": 14103488781,
          "guarded_transition_cpu_ns": 28066510014,
          "current_hard_value_generator_calls": 4,
          "current_hard_value_generator_examples": 512,
          "current_hard_value_generator_refinement_examples": 512,
          "current_hard_value_reward_observer_calls": 8,
          "current_hard_value_reward_observer_digit_examples": 1024,
          "directional_generator_calls": 2,
          "directional_generator_examples": 96,
          "directional_generator_refinement_examples": 96,
          "directional_teacher_calls": 2,
          "directional_teacher_examples": 96,
          "directional_teacher_refinement_examples": 96,
          "directional_backward_calls": 1,
          "directional_backward_examples": 96,
          "directional_gradient_measurements": 1,
          "adapt_feature_probe_calls": 4,
          "adapt_feature_probe_examples": 512,
          "adapt_feature_probe_refinement_examples": 512,
          "clean_feature_probe_calls": 2,
          "clean_feature_probe_examples": 256,
          "clean_feature_probe_refinement_examples": 256,
          "feature_probe_reverse_calls": 3,
          "feature_probe_reverse_examples": 1280,
          "margin_generator_calls": 4,
          "margin_generator_examples": 512,
          "margin_generator_refinement_examples": 512,
          "margin_reward_observer_calls": 8,
          "margin_reward_observer_digit_examples": 1024,
          "accepted_blocks": 6
        },
        "wall_seconds": 19.603226630999416
      },
      {
        "kind": "engineering_preflight",
        "receipt_sha256": "5dee785a445179b6bc20bc733c617438690c915668104d1a74cab4314175fb3c",
        "gradient_microsteps": 432,
        "ledger": {
          "original_guard_generator_calls": 2,
          "original_guard_generator_examples": 256,
          "original_guard_generator_refinement_examples": 256,
          "original_guard_reward_observer_calls": 4,
          "original_guard_reward_observer_digit_examples": 512,
          "cold_cache_initialization_generator_calls": 1,
          "cold_cache_initialization_generator_examples": 128,
          "cold_cache_initialization_generator_refinement_examples": 128,
          "cold_cache_initialization_reward_observer_calls": 2,
          "cold_cache_initialization_reward_observer_digit_examples": 256,
          "state_capture_wall_ns": 639048770,
          "state_capture_cpu_ns": 672913499,
          "state_serialize_wall_ns": 187951678,
          "state_serialize_cpu_ns": 187991349,
          "serialized_branch_bytes": 3173018,
          "complete_branch_restores": 10,
          "state_restore_wall_ns": 2244308604,
          "state_restore_cpu_ns": 2243893264,
          "transaction_snapshots": 9,
          "gradient_generator_calls": 864,
          "gradient_generator_examples": 41472,
          "gradient_generator_refinement_examples": 41472,
          "gradient_teacher_calls": 864,
          "gradient_teacher_examples": 41472,
          "gradient_teacher_refinement_examples": 41472,
          "gradient_backward_calls": 432,
          "gradient_backward_examples": 41472,
          "optimizer_steps": 336,
          "scheduled_gradient_microsteps": 432,
          "candidate_guard_generator_calls": 18,
          "candidate_guard_generator_examples": 2304,
          "candidate_guard_generator_refinement_examples": 2304,
          "candidate_guard_reward_observer_calls": 36,
          "candidate_guard_reward_observer_digit_examples": 4608,
          "rejected_blocks": 3,
          "discarded_gradient_microsteps": 144,
          "guarded_transition_wall_ns": 13872425271,
          "guarded_transition_cpu_ns": 27682356867,
          "current_hard_value_generator_calls": 4,
          "current_hard_value_generator_examples": 512,
          "current_hard_value_generator_refinement_examples": 512,
          "current_hard_value_reward_observer_calls": 8,
          "current_hard_value_reward_observer_digit_examples": 1024,
          "directional_generator_calls": 2,
          "directional_generator_examples": 96,
          "directional_generator_refinement_examples": 96,
          "directional_teacher_calls": 2,
          "directional_teacher_examples": 96,
          "directional_teacher_refinement_examples": 96,
          "directional_backward_calls": 1,
          "directional_backward_examples": 96,
          "directional_gradient_measurements": 1,
          "adapt_feature_probe_calls": 4,
          "adapt_feature_probe_examples": 512,
          "adapt_feature_probe_refinement_examples": 512,
          "clean_feature_probe_calls": 2,
          "clean_feature_probe_examples": 256,
          "clean_feature_probe_refinement_examples": 256,
          "feature_probe_reverse_calls": 3,
          "feature_probe_reverse_examples": 1280,
          "margin_generator_calls": 4,
          "margin_generator_examples": 512,
          "margin_generator_refinement_examples": 512,
          "margin_reward_observer_calls": 8,
          "margin_reward_observer_digit_examples": 1024,
          "accepted_blocks": 6
        },
        "wall_seconds": 19.00305874300102
      }
    ],
    "failed_attempts": [
      {
        "receipt": {
          "schema": "hepta.fullstudy.infrastructure-failure.1",
          "observed_utc": "2026-10-29T07:48:24.201206+00:00",
          "status": "INCOMPLETE_INFRASTRUCTURE_FAILURE",
          "last_progress": {
            "running": {
              "A-17": {
                "pid": 409403,
                "last_line": "{\"stage\": \"A_bank\", \"seed\": 17, \"schedule\": 6003, \"prefix\": \"balanced\", \"step\": 0, \"rows\": 43}"
              },
              "A-29": {
                "pid": 409404,
                "last_line": "{\"stage\": \"A_bank\", \"seed\": 29, \"schedule\": 6003, \"prefix\": \"balanced\", \"step\": 0, \"rows\": 43}"
              },
              "A-43": {
                "pid": 409405,
                "last_line": "{\"stage\": \"A_bank\", \"seed\": 43, \"schedule\": 6003, \"prefix\": \"balanced\", \"step\": 0, \"rows\": 43}"
              },
              "C": {
                "pid": 414131,
                "last_line": "{\"stage\": \"C_warmup\", \"seed\": 808, \"mode\": \"dual\", \"role\": \"evaluation\", \"complete\": true}"
              }
            },
            "pending": [],
            "results": {
              "preflight": {
                "exit_code": 0,
                "wall_seconds": 22.016673221995006,
                "last_line": "{\"complete\": true, \"full_current_dimension\": 54740, \"wall_seconds\": 19.00305874300102}"
              }
            },
            "raw_bytes": 410254736,
            "elapsed_seconds": 1381.6519133149995
          },
          "cause_observed": "exec-server transport disconnected, then controller and all four study workers absent; unpinned private tmpfs namespace vanished",
          "root_cause_confirmed": false,
          "raw_namespace_lost": true,
          "raw_archive_finalized": false,
          "published_source_preserved": true,
          "independent_endpoint_roles_opened": [],
          "scientific_completeness_claim": false,
          "rerun_rule": "Repeat exact frozen A/C configuration without seed/action/threshold/sample selection; record failed-attempt work separately, unknown unpersisted work not fabricated.",
          "memory_observations": {
            "memory_max_bytes": 8589934592,
            "memory_peak_bytes": 8594927616,
            "oom_events_cumulative": 8,
            "oom_kill_cumulative": 4,
            "memory_events_tied_to_specific_pid": false,
            "interpretation": "Consistent with memory pressure; event counters alone do not identify each terminated process."
          },
          "retry_storage": "process-independent scratch filesystem, new root",
          "empty_archive_reservation_released": true,
          "known_scheduled_gradient_microsteps_lower_bound": {
            "A_per_seed": 31440,
            "A_all_three": 94320,
            "C_completed_warmups": 8000,
            "attempt01_training_total": 102320,
            "attempt01_preflight": 432,
            "earlier_disk_preflight": 432,
            "all_known_before_retry": 103184,
            "A_formula": "43 logged parents per seed: 7 complete prefixes*sum_d=0..5(4*(288\u221248*d)+48)+1200; each full prefix4320",
            "unlogged_partial_work": "unknown; lower bound is not the complete actual compute cost"
          }
        },
        "training_microsteps_lower_bound": 102320,
        "engineering_microsteps_included": 0,
        "unknown_additional_work": true
      }
    ],
    "gradient_microsteps_known_lower_bound": 103184,
    "unknown_partial_work": true,
    "scope": "Only receipt-backed work supplied here; inclusive historical subtotal keys are not added again."
  }
}
```
