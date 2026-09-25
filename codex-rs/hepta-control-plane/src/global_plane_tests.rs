use std::fmt::Debug;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::ReplayWindow;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_fleet::lease_ledger::AllocationGrant;
use codex_hepta_fleet::lease_ledger::HostObservation;
use codex_hepta_fleet::lease_ledger::LeaseLedger;
use codex_hepta_fleet::lease_ledger::Resources;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::FLEET_ACCELERATOR_MILLIS_AXIS;
use super::FLEET_CPU_MILLIS_AXIS;
use super::FLEET_MEMORY_MIB_AXIS;
use super::FleetEssentialFloorsV1;
use super::GlobalPlaneError;
use super::admit_fleet_allocation_owner_v1;
use super::authenticate_owner_summary_v1;
use super::compose_global_plan_with_fleet_v1;
use super::owner_summary_payload_digest_v1;
use super::owner_summary_scope_digest_v1;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningRequestV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::canonical_resource_reservation_digest;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(_) => panic!("expected an error"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn fleet_ledger(cpu_millis: u64) -> LeaseLedger {
    let mut ledger = LeaseLedger::new();
    must(ledger.admit_host(HostObservation {
        host_id: "host-a".to_string(),
        failure_domain_id: "rack-a".to_string(),
        generation: 3,
        observed_at_ms: 900,
        valid_until_ms: 6_000,
        capacity: Resources {
            cpu_millis: 200,
            memory_bytes: 64 * 1024 * 1024,
            accelerator_millis: 20,
        },
    }));
    must(ledger.issue(
        1_000,
        AllocationGrant {
            allocation_id: "allocation:global-1".to_string(),
            request_id: "request:global-1".to_string(),
            principal_id: "agent:alpha".to_string(),
            host_id: "host-a".to_string(),
            failure_domain_id: "rack-a".to_string(),
            host_generation: 3,
            authority_epoch: 7,
            lease_generation: 5,
            expires_at_ms: 5_000,
            resources: Resources {
                cpu_millis,
                memory_bytes: 32 * 1024 * 1024,
                accelerator_millis: 10,
            },
            semantic_digest: digest("fleet-allocation").to_string(),
            revoked: false,
        },
    ));
    ledger
}

fn evidence_owner(
    objective: Digest32,
    generation: Generation,
    configuration: Digest32,
) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id("kernel.evidence"),
        revision: must(Revision::new(9)),
        objective_digest: objective,
        body_generation: generation,
        configuration_digest: configuration,
        observed_at_micros: 95,
        expires_at_micros: 195,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("evidence-frontier"),
        support_digest: digest("evidence-support"),
    }
}

fn sign_owner(summary: &OwnerSummaryV1) -> (SignedMessage, IssuerRegistration) {
    let signing = SigningKey::from_bytes(&[21; 32]);
    let claims = SignedMessageClaims {
        issuer_id: id("issuer:evidence"),
        key_epoch: must(Generation::new(4)),
        message_id: id("message:evidence:9"),
        subject_id: summary.owner_id.clone(),
        scope_digest: owner_summary_scope_digest_v1(summary),
        payload_digest: owner_summary_payload_digest_v1(summary),
        sequence: 9,
        expires_at_ms: 5_000,
    };
    let signature = signing.sign(&claims.signing_bytes()).to_bytes();
    (
        SignedMessage { claims, signature },
        IssuerRegistration {
            issuer_id: id("issuer:evidence"),
            key_epoch: must(Generation::new(4)),
            verifying_key: signing.verifying_key(),
            revoked: false,
        },
    )
}

fn candidate(name: &str, owners: &[StableId]) -> PlanCandidateV1 {
    let work = name == "work";
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation:{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: owners.to_vec(),
        final_payload_digests: work.then(|| digest("effect-payload")).into_iter().collect(),
        resource_costs: vec![
            PlannerAxisValueV1 {
                axis: id(FLEET_CPU_MILLIS_AXIS),
                value: if work { q32(20) } else { FixedQ32::ZERO },
            },
            PlannerAxisValueV1 {
                axis: id(FLEET_MEMORY_MIB_AXIS),
                value: if work { q32(4) } else { FixedQ32::ZERO },
            },
            PlannerAxisValueV1 {
                axis: id(FLEET_ACCELERATOR_MILLIS_AXIS),
                value: if work { q32(2) } else { FixedQ32::ZERO },
            },
        ],
    }
}

fn ndu_input(
    objective: Digest32,
    generation: Generation,
    owners: &[StableId],
) -> NduPlanningInputV1 {
    let utility_axis = id("global-utility");
    let profile = UtilityProfile {
        profile_id: id("global-control-profile"),
        axis_registry_digest: digest("global-control-axis-registry"),
        normalization_manifest_digest: digest("global-control-normalization"),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: owners.to_vec(),
        },
    };
    let mut input = NduPlanningInputV1 {
        policy: must(legacy_evaluation_policy(&profile)),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: objective,
            generation,
            contributions: Vec::new(),
        },
    };
    for candidate_id in ["abstain", "work"] {
        for organ_id in owners {
            input.contributions.contributions.push(UtilityContribution {
                candidate_id: id(candidate_id),
                organ_id: organ_id.clone(),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: utility_axis.clone(),
                    value: if candidate_id == "work" {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: vec![],
                resource: vec![],
                uncertainty: vec![AxisValue {
                    axis: utility_axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest(&format!("{candidate_id}:{}", organ_id.as_str())),
            });
        }
    }
    input
}

fn compose(cpu_millis: u64) -> crate::GlobalControlPlanV1 {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = must(Generation::new(11));
    let fleet = must(admit_fleet_allocation_owner_v1(
        &fleet_ledger(cpu_millis),
        "allocation:global-1",
        "agent:alpha",
        objective,
        generation,
        configuration,
        1_100,
        90,
        190,
        FleetEssentialFloorsV1 {
            cpu_millis: 10,
            memory_bytes: 2 * 1024 * 1024,
            accelerator_millis: 2,
        },
    ));
    let raw_evidence = evidence_owner(objective, generation, configuration);
    let (signed, issuer) = sign_owner(&raw_evidence);
    let mut replay = ReplayWindow::new(16);
    let evidence = must(authenticate_owner_summary_v1(
        raw_evidence,
        &signed,
        &issuer,
        &mut replay,
        1_100,
    ));
    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let ndu = ndu_input(objective, generation, &owners);
    let policy = must(canonical_ndu_planning_policy_digest(&ndu));
    must(compose_global_plan_with_fleet_v1(
        SnapshotRequestV1 {
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            revocation_frontier_digest: digest("revocation-frontier"),
            snapshot_policy_digest: digest("global-snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 20,
            expires_at_micros: 200,
            required_owner_ids: owners.clone(),
        },
        fleet,
        vec![evidence],
        PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 0,
            deadline_micros: 180,
            evaluation_policy_digest: policy,
            resource_profile_digest: digest("overwritten-by-fleet"),
            candidates: vec![candidate("abstain", &owners), candidate("work", &owners)],
            resource_reservations: Vec::new(),
        },
        ndu,
        100,
    ))
}

#[test]
fn authenticated_global_plan_uses_real_fleet_budget_and_ndu() {
    let result = compose(80);
    assert_eq!(
        result.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
    );
    assert_eq!(
        result.prepared.resource_reservation_digest(),
        must(canonical_resource_reservation_digest(&[
            crate::ResourceReservationV1 {
                axis: id(FLEET_CPU_MILLIS_AXIS),
                endowment: q32(80),
                essential_floor: q32(10),
            },
            crate::ResourceReservationV1 {
                axis: id(FLEET_MEMORY_MIB_AXIS),
                endowment: q32(32),
                essential_floor: q32(2),
            },
            crate::ResourceReservationV1 {
                axis: id(FLEET_ACCELERATOR_MILLIS_AXIS),
                endowment: q32(10),
                essential_floor: q32(2),
            },
        ]))
    );
    let requests = match result.grant_requests {
        Some(requests) => requests,
        None => panic!("selected work plan must emit grant requests"),
    };
    assert_eq!(requests.requests().len(), 1);
    assert!(!requests.authority().grants_any());
}

#[test]
fn different_real_fleet_budget_changes_the_sealed_plan_identity() {
    let first = compose(80);
    let second = compose(100);
    assert_eq!(
        first.prepared.candidate_set_digest(),
        second.prepared.candidate_set_digest()
    );
    assert_ne!(
        first.prepared.resource_reservation_digest(),
        second.prepared.resource_reservation_digest()
    );
    assert_ne!(
        first.prepared.prepared_digest(),
        second.prepared.prepared_digest()
    );
}

#[test]
fn replayed_owner_summary_is_rejected_before_planning() {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = must(Generation::new(11));
    let summary = evidence_owner(objective, generation, configuration);
    let (signed, issuer) = sign_owner(&summary);
    let mut replay = ReplayWindow::new(16);
    let _first = must(authenticate_owner_summary_v1(
        summary.clone(),
        &signed,
        &issuer,
        &mut replay,
        1_100,
    ));
    assert!(matches!(
        must_err(authenticate_owner_summary_v1(
            summary,
            &signed,
            &issuer,
            &mut replay,
            1_100,
        )),
        GlobalPlaneError::Authentication(codex_hepta_authbus::Error::Replay)
    ));
}
