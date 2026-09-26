use std::error::Error;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;

fn fixture() -> Result<(SnapshotRequestV1, OwnerSummaryV1, PlanningRequestV1), Box<dyn Error>> {
    let owner = StableId::new("owner")?;
    let axis = StableId::new("compute")?;
    let digest = Digest32::of_bytes(b"fixture");
    let generation = Generation::new(1)?;
    let snapshot = SnapshotRequestV1 {
        objective_digest: digest,
        body_generation: generation,
        configuration_digest: digest,
        revocation_frontier_digest: digest,
        snapshot_policy_digest: digest,
        collected_at_micros: 100,
        maximum_owner_age_micros: 10,
        expires_at_micros: 200,
        required_owner_ids: vec![owner.clone()],
    };
    let summary = OwnerSummaryV1 {
        owner_id: owner.clone(),
        revision: Revision::new(1)?,
        objective_digest: digest,
        body_generation: generation,
        configuration_digest: digest,
        observed_at_micros: 100,
        expires_at_micros: 200,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest,
        support_digest: digest,
    };
    let request = PlanningRequestV1 {
        plan_id: StableId::new("plan")?,
        now_micros: 100,
        deadline_micros: 190,
        evaluation_policy_digest: digest,
        resource_profile_digest: digest,
        candidates: vec![
            PlanCandidateV1 {
                candidate_id: StableId::new("abstain")?,
                operation_id: StableId::new("abstain")?,
                plan_digest: digest,
                required_owner_ids: vec![owner.clone()],
                final_payload_digests: vec![],
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: axis.clone(),
                    value: FixedQ32::ZERO,
                }],
            },
            PlanCandidateV1 {
                candidate_id: StableId::new("work")?,
                operation_id: StableId::new("work")?,
                plan_digest: digest,
                required_owner_ids: vec![owner],
                final_payload_digests: vec![digest],
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: axis.clone(),
                    value: FixedQ32::ZERO,
                }],
            },
        ],
        resource_reservations: vec![ResourceReservationV1 {
            axis,
            endowment: FixedQ32::ZERO,
            essential_floor: FixedQ32::ZERO,
        }],
    };
    Ok((snapshot, summary, request))
}

#[test]
fn optional_owner_cannot_poison_v1_snapshot() -> Result<(), Box<dyn Error>> {
    let (request, summary, _) = fixture()?;
    for readiness in [OwnerReadinessV1::Ready, OwnerReadinessV1::Unavailable] {
        let mut extra = summary.clone();
        extra.owner_id = StableId::new("unrequested")?;
        extra.readiness = readiness;
        assert_eq!(
            crate::collect_snapshot(request.clone(), vec![summary.clone(), extra]),
            Err(PlannerError::IncompleteSnapshot)
        );
    }
    Ok(())
}

#[test]
fn duplicate_payload_is_rejected_before_normalization() -> Result<(), Box<dyn Error>> {
    let (snapshot, owner, mut request) = fixture()?;
    let snapshot = crate::collect_snapshot(snapshot, vec![owner])?;
    request.candidates[1].final_payload_digests.push(Digest32::of_bytes(b"fixture"));
    assert_eq!(
        crate::prepare_plan(&snapshot, request),
        Err(PlannerError::PreparedPlanMismatch)
    );
    Ok(())
}

#[test]
fn abstain_never_requests_an_effect() -> Result<(), Box<dyn Error>> {
    let (snapshot, owner, mut request) = fixture()?;
    let snapshot = crate::collect_snapshot(snapshot, vec![owner])?;
    request.candidates[0].final_payload_digests.push(Digest32::of_bytes(b"effect"));
    assert_eq!(
        crate::prepare_plan(&snapshot, request),
        Err(PlannerError::AbstainUnavailable)
    );
    Ok(())
}

#[test]
fn backward_clock_is_not_a_fresh_snapshot() -> Result<(), Box<dyn Error>> {
    let (snapshot, owner, mut request) = fixture()?;
    let snapshot = crate::collect_snapshot(snapshot, vec![owner])?;
    request.now_micros = 99;
    assert!(matches!(
        crate::prepare_plan(&snapshot, request),
        Err(PlannerError::InvalidTime(_))
    ));
    Ok(())
}

#[test]
fn excessive_axes_are_rejected_before_sorting() -> Result<(), Box<dyn Error>> {
    let (snapshot, owner, mut request) = fixture()?;
    let snapshot = crate::collect_snapshot(snapshot, vec![owner])?;
    request.candidates[1].resource_costs = vec![request.candidates[1].resource_costs[0].clone(); 33];
    assert_eq!(
        crate::prepare_plan(&snapshot, request),
        Err(PlannerError::LimitExceeded("candidate resource axes"))
    );
    Ok(())
}
