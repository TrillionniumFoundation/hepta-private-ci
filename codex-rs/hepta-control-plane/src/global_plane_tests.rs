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
use ed25519_dalek::Signer;
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

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn fleet_ledger() -> LeaseLedger {
    let mut ledger = LeaseLedger::new();
    ledger
        .admit_host(HostObservation {
            host_id: "host-a".to_string(),
            failure_domain_id: "rack-a".to_string(),
            generation: 3,
            observed_at_ms: 900,
            valid_until_ms: 6_000,
            capacity: Resources {
                cpu_millis: 100,
                memory_bytes: 64 * 1024 * 1024,
                accelerator_millis: 20,
            },
        })
        .expect("host observation");
    ledger
        .issue(
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
                    cpu_millis: 80,
                    memory_bytes: 32 * 1024 * 1024,
                    accelerator_millis: 10,
                },
                semantic_digest: digest("fleet-allocation").to_string(),
                revoked: false,
            },
        )
        .expect("allocation grant");
    ledger
}

fn evidence_owner(
    objective: Digest32,
    generation: Generation,
    configuration: Digest32,
) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id("kernel.evidence"),
        revision: Revision::new(9).expect("revision"),
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
        key_epoch: Generation::new(4).expect("key epoch"),
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
            key_epoch: Generation::new(4).expect("key epoch"),
            verifying_key: signing.verifying_key(),
            revoked: false,
        },
    )
}

fn candidate(
    name: &str,
    owners: &[StableId],
    cpu: i64,
    memory_mib: i64,
    accelerator: i64,
) -> PlanCandidateV1 {
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation:{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: owners.to_vec(),
        final_payload_digests: if name == "abstain" {
            Vec::new()
        } else {
            vec![digest("effect-payload")]
        },
        resource_costs: vec![
            PlannerAxisValueV1 {
                axis: id(FLEET_CPU_MILLIS_AXIS),
                value: q32(cpu),
            },
            PlannerAxisValueV1 {
                axis: id(FLEET_MEMORY_MIB_AXIS),
                value: q32(memory_mib),
            },
            PlannerAxisValueV1 {
                axis: id(FLEET_ACCELERATOR_MILLIS_AXIS),
                value: q32(accelerator),
            },
        ],
    }
}

#[test]
fn authenticated_multi_owner_fleet_plan_runs_real_ndu_and_emits_deny_all_request() {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let ledger = fleet_ledger();
    let fleet = admit_fleet_allocation_owner_v1(
        &ledger,
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
    )
    .expect("fleet admission");

    let raw_evidence = evidence_owner(objective, generation, configuration);
    let (signed, issuer) = sign_owner(&raw_evidence);
    let mut replay = ReplayWindow::new(16);
    let evidence =
        authenticate_owner_summary_v1(raw_evidence, &signed, &issuer, &mut replay, 1_100)
            .expect("signed evidence owner admission");

    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let candidates = vec![
        candidate("abstain", &owners, 0, 0, 0),
        candidate("work", &owners, 20, 4, 2),
    ];

    let utility_axis = id("global-utility");
    let profile = UtilityProfile {
        profile_id: id("global-control-profile"),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: owners.clone(),
        },
    };
    let mut ndu = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("legacy policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: objective,
            generation,
            contributions: Vec::new(),
        },
    };
    for candidate_id in ["abstain", "work"] {
        for organ_id in &owners {
            ndu.contributions.contributions.push(UtilityContribution {
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
    let evaluation_policy_digest =
        canonical_ndu_planning_policy_digest(&ndu).expect("NDU policy digest");

    let result = compose_global_plan_with_fleet_v1(
        SnapshotRequestV1 {
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            revocation_frontier_digest: digest("revocation-frontier"),
            snapshot_policy_digest: digest("global-snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 20,
            expires_at_micros: 200,
            required_owner_ids: owners,
        },
        fleet,
        vec![evidence],
        PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 0,
            deadline_micros: 180,
            evaluation_policy_digest,
            resource_profile_digest: digest("overwritten-by-fleet"),
            candidates,
            resource_reservations: Vec::new(),
        },
        ndu,
        100,
    )
    .expect("global plan");

    assert_eq!(
        result.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
    );
    let requests = result.grant_requests.expect("unique plan emits requests");
    assert_eq!(requests.requests().len(), 1);
    assert_eq!(
        requests.requests()[0].final_payload_digest,
        digest("effect-payload")
    );
    assert!(!requests.authority().grants_any());
}

#[test]
fn owner_admission_consumes_replay_sequence() {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (signed, issuer) = sign_owner(&summary);
    let mut replay = ReplayWindow::new(16);

    authenticate_owner_summary_v1(summary.clone(), &signed, &issuer, &mut replay, 1_100)
        .expect("first signed owner admission");
    assert!(matches!(
        authenticate_owner_summary_v1(summary, &signed, &issuer, &mut replay, 1_100),
        Err(GlobalPlaneError::Authentication(
            codex_hepta_authbus::Error::Replay
        ))
    ));
}

#[test]
fn global_composition_rejects_missing_authenticated_owner() {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let fleet = admit_fleet_allocation_owner_v1(
        &fleet_ledger(),
        "allocation:global-1",
        "agent:alpha",
        objective,
        generation,
        configuration,
        1_100,
        90,
        190,
        FleetEssentialFloorsV1::default(),
    )
    .expect("fleet admission");

    let profile = UtilityProfile {
        profile_id: id("empty-profile"),
        dimensions: vec![(id("utility"), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("runtime.fleet")],
        },
    };
    let ndu = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: objective,
            generation,
            contributions: Vec::new(),
        },
    };

    let error = compose_global_plan_with_fleet_v1(
        SnapshotRequestV1 {
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 20,
            expires_at_micros: 200,
            required_owner_ids: vec![id("runtime.fleet"), id("kernel.evidence")],
        },
        fleet,
        Vec::new(),
        PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 0,
            deadline_micros: 180,
            evaluation_policy_digest: digest("unused"),
            resource_profile_digest: digest("unused"),
            candidates: Vec::new(),
            resource_reservations: Vec::new(),
        },
        ndu,
        100,
    )
    .expect_err("required owner without admission must fail before planning");
    assert!(matches!(error, GlobalPlaneError::OwnerSetMismatch));
}
