use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn percentile(values: &[u128], percentile: usize) -> u128 {
    let index = (values.len() - 1) * percentile / 100;
    values[index]
}

#[test]
#[ignore = "named-host qualification measurement"]
fn planner_named_host_profile() {
    let generation = Generation::new(1).expect("generation");
    let owners: Vec<_> = (0..32)
        .map(|index| OwnerSummaryV1 {
            owner_id: id(&format!("owner-{index:02}")),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 999,
            expires_at_micros: 10_000,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest(&format!("frontier-{index}")),
            support_digest: digest(&format!("support-{index}")),
        })
        .collect();
    let required_owner_ids = owners.iter().map(|owner| owner.owner_id.clone()).collect();
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 10_000,
            required_owner_ids,
        },
        owners,
    )
    .expect("snapshot");
    let reservations: Vec<_> = (0..32)
        .map(|index| ResourceReservationV1 {
            axis: id(&format!("axis-{index:02}")),
            endowment: q32(1_000),
            essential_floor: q32(100),
        })
        .collect();
    let candidates: Vec<_> = (0..128)
        .map(|index| {
            let name = if index == 0 {
                "abstain".to_string()
            } else {
                format!("candidate-{index:03}")
            };
            PlanCandidateV1 {
                candidate_id: id(&name),
                operation_id: id(&format!("operation-{index:03}")),
                plan_digest: digest(&format!("plan-{index}")),
                required_owner_ids: vec![id("owner-00")],
                final_payload_digests: vec![],
                resource_costs: (0..32)
                    .map(|axis| PlannerAxisValueV1 {
                        axis: id(&format!("axis-{axis:02}")),
                        value: if index == 0 {
                            FixedQ32::ZERO
                        } else {
                            q32(1)
                        },
                    })
                    .collect(),
            }
        })
        .collect();
    let resource_profile_digest =
        canonical_resource_profile_digest(&reservations).expect("resource profile");
    let candidate_ids: Vec<_> = candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();

    let mut planning_micros = Vec::new();
    for iteration in 0..200_u64 {
        let start = Instant::now();
        let prepared = prepare_plan(
            &snapshot,
            PlanningRequestV1 {
                plan_id: id(&format!("perf-{iteration}")),
                now_micros: 1_000,
                deadline_micros: 9_000,
                evaluation_policy_digest: digest("evaluation-policy"),
                resource_profile_digest,
                candidates: candidates.clone(),
                resource_reservations: reservations.clone(),
            },
        )
        .expect("prepare");
        let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            evaluation_policy_digest: digest("evaluation-policy"),
            evaluation_digest: digest("ndu-evaluation"),
            evaluated_candidate_ids: candidate_ids.clone(),
            rejected_candidate_ids: vec![],
            pareto_candidate_ids: vec![id("abstain")],
            advisory_candidate_id: Some(id("abstain")),
            uncertainty_digest: digest("uncertainty"),
            disposition: PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain,
        })
        .expect("bind");
        finalize_plan(&snapshot, &prepared, &evaluation, 1_100).expect("finalize");
        planning_micros.push(start.elapsed().as_micros());
    }
    planning_micros.sort_unstable();

    let mut journal = crate::PlannerJournalV1::new();
    for index in 0..4096 {
        let value = digest(&format!("journal-{index}"));
        journal
            .append(crate::PlannerJournalKindV1::Snapshot, value, value)
            .expect("append");
    }
    let journal_bytes = journal.export_bytes();
    let mut reopen_micros = Vec::new();
    for _ in 0..30 {
        let start = Instant::now();
        crate::PlannerJournalV1::reopen(&journal_bytes).expect("reopen");
        reopen_micros.push(start.elapsed().as_micros());
    }
    reopen_micros.sort_unstable();

    println!(
        "CONTROL_RUNTIME_BENCH_JSON {{\"owners\":32,\"candidates\":128,\"axes\":32,\"planning_p50_us\":{},\"planning_p95_us\":{},\"planning_p99_us\":{},\"journal_records\":4096,\"journal_reopen_p95_us\":{},\"journal_reopen_p99_us\":{}}}",
        percentile(&planning_micros, 50),
        percentile(&planning_micros, 95),
        percentile(&planning_micros, 99),
        percentile(&reopen_micros, 95),
        percentile(&reopen_micros, 99),
    );
}
