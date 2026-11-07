use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::differentiation_demand::*;
use crate::differentiation_types::*;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) fn actor(name: &str) -> DifferentiationActorV1 {
    DifferentiationActorV1 {
        principal: id(name),
        signing_key_digest: digest(&format!("key:{name}")),
        credential_chain_digest: digest(&format!("credential:{name}")),
        controller_digest: digest(&format!("controller:{name}")),
    }
}

pub(super) fn request() -> DifferentiationPlanRequestV1 {
    DifferentiationPlanRequestV1 {
        study_id: id("study:1"),
        module_id: id("module:memory"),
        partition_id: id("partition:code"),
        parent: DifferentiationParentV1 {
            artifact_digest: digest("parent"),
            topology_digest: digest("parent-topology"),
            capability_digest: digest("capability"),
            state_schema_digest: digest("state-schema"),
            checkpoint_digest: digest("checkpoint"),
            generation: Generation::new(5).expect("generation"),
            namespace: id("parent:shared"),
        },
        candidate_namespace: id("nursery:child"),
        frozen_at_ms: 10,
        demand: DifferentiationDemandPolicyV1 {
            starts_at_ms: 20,
            window_width_ms: 10,
            required_windows: 3,
            minimum_tasks_per_window: 2,
            minimum_error_ppm: 500_000,
            minimum_diagnosis_ppm: 500_000,
            diagnosis: DifferentiationDiagnosisV1::NegativeTransfer,
            trigger: DifferentiationTriggerV1::PersistentError,
            measurement_protocol_digest: digest("diagnosis-protocol"),
        },
        study: DifferentiationStudyPolicyV1 {
            opens_at_ms: 70,
            deadline_at_ms: 100,
            cost_profile_digest: digest("cost-profile"),
            outcome_protocol_digest: digest("outcome-protocol"),
            maximum_cost_per_arm: 1_000,
            maximum_total_study_cost: 6_000,
            cost_penalty_ppm_per_unit: 1,
            minimum_net_gain_ppm_per_task: 50_000,
            maximum_retention_regression_ppm: 20_000,
            maximum_migration_regression_ppm: 10_000,
        },
        arm_protocols: ARMS
            .into_iter()
            .map(|arm| (arm, digest(&format!("protocol:{arm:?}"))))
            .collect(),
        new_task_ids: vec![id("new:1"), id("new:2")],
        retention_panels: vec![DifferentiationRetentionPanelV1 {
            slice_id: id("retention:old"),
            task_ids: vec![id("old:1"), id("old:2")],
        }],
        actors: DifferentiationActorsV1 {
            generator: actor("generator"),
            evaluator: actor("evaluator"),
            outcome_observer: actor("observer"),
        },
        compatibility_plan_digest: digest("compatibility"),
        migration_plan_digest: digest("migration"),
        rollback_plan_digest: digest("rollback"),
    }
}

pub(super) fn windows(plan: &DifferentiationPlanV1) -> Vec<DifferentiationDemandWindowV1> {
    let r = &plan.request;
    (0..r.demand.required_windows)
        .map(|i| {
            let starts_at_ms = r.demand.starts_at_ms + u64::from(i) * r.demand.window_width_ms;
            DifferentiationDemandWindowV1 {
                window_id: id(&format!("window:{i}")),
                starts_at_ms,
                ends_at_ms: starts_at_ms + r.demand.window_width_ms,
                parent_artifact_digest: r.parent.artifact_digest,
                parent_generation: r.parent.generation,
                partition_id: r.partition_id.clone(),
                diagnosis: r.demand.diagnosis,
                measurement_protocol_digest: r.demand.measurement_protocol_digest,
                cases: (0..r.demand.minimum_tasks_per_window)
                    .map(|j| DifferentiationDemandCaseV1 {
                        task_id: id(&format!("demand:{i}:{j}")),
                        error_ppm: 900_000,
                        diagnosis_ppm: 800_000,
                        observation_digest: digest(&format!("observation:{i}:{j}")),
                    })
                    .collect(),
                evidence_digest: digest(&format!("window:{i}")),
            }
        })
        .collect()
}
