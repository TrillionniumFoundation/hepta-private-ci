use std::fmt::Debug;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn percentile(values: &mut [u128], percentile: usize) -> u128 {
    values.sort_unstable();
    let index = ((values.len() - 1) * percentile).div_ceil(100);
    values[index]
}

#[test]
#[ignore = "named-host qualification profile; run explicitly with --ignored"]
fn planner_named_host_profile() {
    const ITERATIONS: usize = 200;
    let generation = must(Generation::new(1));
    let owners = (0..MAX_OWNERS)
        .map(|index| id(&format!("owner-{index:02}")))
        .collect::<Vec<_>>();
    let owner_summaries = owners
        .iter()
        .map(|owner| OwnerSummaryV1 {
            owner_id: owner.clone(),
            revision: must(Revision::new(1)),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 1_000,
            expires_at_micros: 10_000,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest(&format!("frontier:{}", owner.as_str())),
            support_digest: digest(&format!("support:{}", owner.as_str())),
        })
        .collect::<Vec<_>>();
    let snapshot_request = SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: generation,
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 1_000,
        maximum_owner_age_micros: 100,
        expires_at_micros: 10_000,
        required_owner_ids: owners.clone(),
    };
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: FixedQ32::from_raw(256_i64 << 32),
        essential_floor: FixedQ32::from_raw(32_i64 << 32),
    }];
    let candidates = (0..MAX_CANDIDATES)
        .map(|index| {
            let abstain = index == 0;
            let candidate_id = if abstain {
                id("abstain")
            } else {
                id(&format!("candidate-{index:03}"))
            };
            PlanCandidateV1 {
                operation_id: if abstain {
                    id("operation-abstain")
                } else {
                    id(&format!("operation-{index:03}"))
                },
                candidate_id,
                plan_digest: digest(&format!("plan:{index}")),
                required_owner_ids: owners[..MAX_REQUIRED_OWNERS_PER_CANDIDATE].to_vec(),
                final_payload_digests: if abstain {
                    vec![]
                } else {
                    vec![digest(&format!("payload:{index}"))]
                },
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("compute"),
                    value: if abstain {
                        FixedQ32::ZERO
                    } else {
                        FixedQ32::ONE
                    },
                }],
            }
        })
        .collect::<Vec<_>>();
    let planning_request = PlanningRequestV1 {
        plan_id: id("profile-plan"),
        now_micros: 1_000,
        deadline_micros: 9_000,
        evaluation_policy_digest: digest("policy"),
        resource_profile_digest: must(canonical_resource_profile_digest(&reservations)),
        candidates,
        resource_reservations: reservations,
    };

    let mut planner_latencies = Vec::with_capacity(ITERATIONS);
    for _ in 0..ITERATIONS {
        let started = Instant::now();
        let snapshot = must(collect_snapshot(
            snapshot_request.clone(),
            owner_summaries.clone(),
        ));
        let prepared = must(prepare_plan(&snapshot, planning_request.clone()));
        let chosen = id("candidate-001");
        let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
            objective_digest: prepared.objective_digest(),
            body_generation: prepared.body_generation(),
            evaluation_policy_digest: prepared.evaluation_policy_digest(),
            evaluation_digest: digest("evaluation"),
            evaluated_candidate_ids: prepared
                .feasible_candidates()
                .iter()
                .map(|candidate| candidate.candidate_id.clone())
                .collect(),
            rejected_candidate_ids: vec![],
            pareto_candidate_ids: vec![chosen.clone()],
            advisory_candidate_id: Some(chosen),
            uncertainty_digest: digest("uncertainty"),
            disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        }));
        let receipt = must(finalize_plan(&snapshot, &prepared, &evaluation, 1_100));
        let grants = must(request_execution_grants(
            &snapshot,
            &prepared,
            &receipt,
            1_100,
        ));
        assert_eq!(grants.requests().len(), 1);
        planner_latencies.push(started.elapsed().as_micros());
    }

    let mut journal = PlannerJournalV1::new();
    for index in 0..4096 {
        must(journal.append(
            PlannerJournalKindV1::Snapshot,
            digest(&format!("identity:{index}")),
            digest(&format!("payload:{index}")),
        ));
    }
    let journal_bytes = journal.export_bytes();
    let mut reopen_latencies = Vec::with_capacity(50);
    for _ in 0..50 {
        let started = Instant::now();
        let reopened = must(PlannerJournalV1::reopen(&journal_bytes));
        assert_eq!(reopened.entries().len(), 4096);
        reopen_latencies.push(started.elapsed().as_micros());
    }

    let mut planner_p95 = planner_latencies.clone();
    let mut reopen_p95 = reopen_latencies.clone();
    println!(
        "CONTROL_RUNTIME_PROFILE iterations={ITERATIONS} planner_p95_us={} planner_p99_us={} journal_records=4096 journal_reopen_p95_us={} journal_reopen_p99_us={}",
        percentile(&mut planner_p95, 95),
        percentile(&mut planner_latencies, 99),
        percentile(&mut reopen_p95, 95),
        percentile(&mut reopen_latencies, 99),
    );
}
