use super::*;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::perception_test_support::observation;
use crate::*;
use pretty_assertions::assert_eq;

fn metrics(wall_micros: u64) -> CellCostMetricsV2 {
    CellCostMetricsV2 {
        wall_micros: Some(wall_micros), cpu_micros: Some(0), energy_microjoules: None,
        storage_read_bytes: Some(0), storage_write_bytes: Some(0), storage_byte_micros: Some(0), communication_bytes: Some(0),
    }
}

fn fixture() -> (PerceptionObservationProposalV1, PerceptionProposalPolicyV1, CellTaskCostV2) {
    let observation = observation();
    let identity = CellTaskCostIdentityV2 { task_digest: d("task").into_array(), source_digest: d("frozen-metering").into_array() };
    let policy = PerceptionProposalPolicyV1 {
        predictor_digest: d("active-predictor"), ndu_snapshot_digest: d("ndu"), cost_identity: identity,
        maximum_total_cost: CellCostMetricsV2 { wall_micros: Some(20), communication_bytes: Some(100), ..CellCostMetricsV2::default() },
        minimum_task_gain_q24: 0,
    };
    let proposal = PerceptionObservationProposalV1 {
        schema: "hepta.perception.proposal.v1".to_owned(), proposal_id: "read-next".to_owned(),
        scope_digest: observation.scope_digest, source_frontier: observation.source_frontier,
        evidence_digest: checked(observation.evidence_digest()).into_array(),
        predictor_digest: policy.predictor_digest.into_array(), ndu_snapshot_digest: policy.ndu_snapshot_digest.into_array(),
        target: PerceptionObservationTargetV1 { source_id: "capture-invoice".to_owned(), origin_digest: observation.evidence[0].source.origin_digest,
            coordinates: PerceptionCoordinatesV1::Bytes { start: 127, end: 150 } },
        expected_task_gain_q24: 1 << 22, estimated_cost: metrics(5),
    };
    let mut cost = checked(CellTaskCostV2::new(identity));
    for stage in [CellCostStageV2::Encoder, CellCostStageV2::Routing, CellCostStageV2::Inference, CellCostStageV2::Training,
        CellCostStageV2::Planning, CellCostStageV2::Critic, CellCostStageV2::Codec, CellCostStageV2::Queue,
        CellCostStageV2::Persistence, CellCostStageV2::Recovery, CellCostStageV2::Communication, CellCostStageV2::Evaluation]
    {
        checked(cost.record(CellCostEntryV2 { event_id: d(&format!("{stage:?}")).into_array(), identity, stage,
            outcome: CellCostOutcomeV2::Succeeded, accounting: CellCostAccountingV2::Exclusive, metrics: metrics(1) }));
    }
    (proposal, policy, cost)
}

#[test]
fn perception_proposal_uses_task_ledger_without_dispatching_or_reserving_work() {
    let (proposal, policy, cost) = fixture();
    let before = cost.clone();
    let assessment = checked(proposal.assess(&observation(), &policy, &cost));
    assert_eq!(assessment, PerceptionProposalAssessmentV1 {
        proposal_digest: Digest32::of_bytes(&checked(serde_json::to_vec(&proposal))),
        cost_ledger_digest: Digest32::of_bytes(&checked(serde_json::to_vec(&cost))),
        disposition: PerceptionProposalDispositionV1::Eligible, authority: AuthorityPosture::DENY_ALL,
    });
    assert_eq!(cost, before);
}

#[test]
fn perception_failed_attempts_remain_charged_while_exact_cost_replay_is_idempotent() {
    let (proposal, policy, mut cost) = fixture();
    let before = checked(cost.summary());
    assert_eq!(checked(cost.record(cost.entries()[0].clone())), CellCostRecordV2::Replayed);
    assert_eq!(checked(cost.summary()), before);
    checked(cost.record(CellCostEntryV2 { event_id: d("failed-read").into_array(), identity: cost.identity(), stage: CellCostStageV2::Communication,
        outcome: CellCostOutcomeV2::Failed, accounting: CellCostAccountingV2::Exclusive, metrics: metrics(6) }));
    assert_eq!(checked(proposal.assess(&observation(), &policy, &cost)).disposition, PerceptionProposalDispositionV1::BudgetExceeded);
}

#[test]
fn perception_unknown_cost_missing_stages_and_overflow_never_create_budget() {
    let (mut proposal, policy, mut cost) = fixture();
    let empty = checked(CellTaskCostV2::new(cost.identity()));
    assert_eq!(checked(proposal.assess(&observation(), &policy, &empty)).disposition, PerceptionProposalDispositionV1::UnmeasuredCost);
    proposal.estimated_cost.wall_micros = None;
    assert_eq!(checked(proposal.assess(&observation(), &policy, &cost)).disposition, PerceptionProposalDispositionV1::UnmeasuredCost);
    proposal.estimated_cost.wall_micros = Some(u64::MAX);
    assert_eq!(checked(proposal.assess(&observation(), &policy, &cost)).disposition, PerceptionProposalDispositionV1::BudgetExceeded);
    proposal.estimated_cost.wall_micros = Some(5);
    checked(cost.record(CellCostEntryV2 { event_id: d("pending-read").into_array(), identity: cost.identity(), stage: CellCostStageV2::Communication,
        outcome: CellCostOutcomeV2::Unknown, accounting: CellCostAccountingV2::Exclusive, metrics: metrics(0) }));
    assert_eq!(checked(proposal.assess(&observation(), &policy, &cost)).disposition, PerceptionProposalDispositionV1::UnmeasuredCost);
}

#[test]
fn perception_proposal_binds_observation_ndu_predictor_and_original_source_extent() {
    let (original, policy, cost) = fixture();
    for (mutation, expected) in [(0, PerceptionProposalErrorV1::StaleObservation), (1, PerceptionProposalErrorV1::BindingMismatch),
        (2, PerceptionProposalErrorV1::BindingMismatch), (3, PerceptionProposalErrorV1::InvalidTarget)]
    {
        let mut proposal = original.clone();
        match mutation {
            0 => proposal.evidence_digest = d("stale").into_array(),
            1 => proposal.predictor_digest = d("unadmitted-predictor").into_array(),
            2 => proposal.ndu_snapshot_digest = d("stale-ndu").into_array(),
            3 => proposal.target.coordinates = PerceptionCoordinatesV1::Bytes { start: 990, end: 1001 },
            _ => unreachable!(),
        }
        assert_eq!(proposal.assess(&observation(), &policy, &cost), Err(expected));
    }
    let mut proposal = original;
    proposal.expected_task_gain_q24 = 0;
    assert_eq!(checked(proposal.assess(&observation(), &policy, &cost)).disposition, PerceptionProposalDispositionV1::InsufficientGain);
    let mut value = checked(serde_json::to_value(&proposal));
    value["execute_authorized"] = serde_json::json!(true);
    assert!(serde_json::from_value::<PerceptionObservationProposalV1>(value).is_err());
}
