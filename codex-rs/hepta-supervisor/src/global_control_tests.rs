use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::RwLock;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_control_plane::EffectBindingV1;
use codex_hepta_control_plane::FLEET_ACCELERATOR_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_CPU_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_MEMORY_MIB_AXIS;
use codex_hepta_control_plane::FleetEssentialFloorsV1;
use codex_hepta_control_plane::GlobalPlaneError;
use codex_hepta_control_plane::GrantRequestV1;
use codex_hepta_control_plane::NduPlanningInputV1;
use codex_hepta_control_plane::OwnerReadinessV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlanCandidateV1;
use codex_hepta_control_plane::PlannerAxisValueV1;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::canonical_effect_binding_digest_v1;
use codex_hepta_control_plane::canonical_ndu_planning_policy_digest;
use codex_hepta_control_plane::final_use_binding_for_grant_request_v1;
use codex_hepta_control_plane::owner_summary_payload_digest_v1;
use codex_hepta_control_plane::owner_summary_scope_digest_v1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_fleet::lease_ledger::AllocationGrant;
use codex_hepta_fleet::lease_ledger::HostObservation;
use codex_hepta_fleet::lease_ledger::LeaseDisposition;
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
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::GlobalControlHostError;
use super::GlobalControlHostPolicyV1;
use super::GlobalControlHostRequestV1;
use super::GlobalControlHostV1;
use super::GlobalOwnerTrustV1;
use super::SignedGlobalOwnerSummaryV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
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
        observed_at_micros: 0,
        expires_at_micros: u64::MAX,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("evidence-frontier"),
        support_digest: digest("evidence-support"),
    }
}

fn sign_owner(summary: &OwnerSummaryV1) -> (SignedMessage, IssuerRegistration) {
    sign_owner_sequence(summary, 9)
}

fn sign_owner_sequence(
    summary: &OwnerSummaryV1,
    sequence: u64,
) -> (SignedMessage, IssuerRegistration) {
    let is_fleet = summary.owner_id.as_str() == "runtime.fleet";
    let signing = SigningKey::from_bytes(&[if is_fleet { 22 } else { 21 }; 32]);
    let issuer_id = if is_fleet { "issuer:fleet" } else { "issuer:evidence" };
    let message_prefix = if is_fleet { "message:fleet" } else { "message:evidence" };
    let claims = SignedMessageClaims {
        issuer_id: id(issuer_id),
        key_epoch: Generation::new(4).expect("key epoch"),
        message_id: id(&format!("{message_prefix}:{sequence}")),
        subject_id: summary.owner_id.clone(),
        scope_digest: owner_summary_scope_digest_v1(summary),
        payload_digest: owner_summary_payload_digest_v1(summary),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = signing.sign(&claims.signing_bytes()).to_bytes();
    (
        SignedMessage { claims, signature },
        IssuerRegistration {
            issuer_id: id(issuer_id),
            key_epoch: Generation::new(4).expect("key epoch"),
            verifying_key: signing.verifying_key(),
            revoked: false,
        },
    )
}

fn fleet_owner(
    objective: Digest32,
    generation: Generation,
    configuration: Digest32,
) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id("runtime.fleet"),
        revision: Revision::new(5).expect("fleet lease revision"),
        objective_digest: objective,
        body_generation: generation,
        configuration_digest: configuration,
        observed_at_micros: 0,
        expires_at_micros: u64::MAX,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("fleet-allocation"),
        support_digest: digest("fleet-support"),
    }
}

fn owner_trusts(evidence_issuer: IssuerRegistration) -> Vec<GlobalOwnerTrustV1> {
    let (_, fleet_issuer) = sign_owner_sequence(
        &fleet_owner(
            digest("global-objective"),
            Generation::new(11).expect("generation"),
            digest("global-configuration"),
        ),
        1,
    );
    vec![
        GlobalOwnerTrustV1 {
            owner_id: id("kernel.evidence"),
            issuer: evidence_issuer,
        },
        GlobalOwnerTrustV1 {
            owner_id: id("runtime.fleet"),
            issuer: fleet_issuer,
        },
    ]
}

fn fleet_ledger() -> LeaseLedger {
    let mut ledger = LeaseLedger::new();
    ledger
        .admit_host(HostObservation {
            host_id: "host-a".to_string(),
            failure_domain_id: "rack-a".to_string(),
            generation: 3,
            observed_at_ms: 900,
            valid_until_ms: u64::MAX,
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
                expires_at_ms: u64::MAX,
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

fn fleet_state() -> Arc<RwLock<LeaseLedger>> {
    Arc::new(RwLock::new(fleet_ledger()))
}

fn host_policy() -> GlobalControlHostPolicyV1 {
    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let ndu = ndu_input(
        digest("global-objective"),
        Generation::new(11).expect("generation"),
        &owners,
    );
    GlobalControlHostPolicyV1 {
        fleet_principal_id: id("agent:alpha"),
        fleet_floors: FleetEssentialFloorsV1 {
            cpu_millis: 10,
            memory_bytes: 2 * 1024 * 1024,
            accelerator_millis: 2,
        },
        required_owner_ids: owners,
        evaluation_policy_digest: canonical_ndu_planning_policy_digest(&ndu)
            .expect("host NDU policy"),
        revocation_frontier_digest: digest("host-revocation-frontier"),
        maximum_owner_age_micros: 60_000_000,
        maximum_plan_lifetime_micros: 5_000_000,
        snapshot_policy_digest: digest("supervisor-global-control-policy"),
    }
}

fn effect_binding() -> EffectBindingV1 {
    EffectBindingV1 {
        subject_id: id("agent:alpha"),
        destination_id: id("provider:effect"),
        scope_digest: digest("effect-scope"),
        effect_boundary_id: id("provider-dispatch"),
    }
}

fn candidate(name: &str, owners: &[StableId]) -> PlanCandidateV1 {
    let work = name == "work";
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation:{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: owners.to_vec(),
        final_payload_digests: if work {
            vec![digest("effect-payload")]
        } else {
            Vec::new()
        },
        effect_binding_digest: work.then(|| {
            canonical_effect_binding_digest_v1(&effect_binding()).expect("effect binding digest")
        }),
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
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: owners.to_vec(),
        },
    };
    let mut input = NduPlanningInputV1 {
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

async fn evidence_store(path: &std::path::Path) -> HeptaEvidenceStore {
    std::fs::create_dir_all(path).expect("evidence directory");
    let absolute = AbsolutePathBuf::try_from(path.to_path_buf()).expect("absolute evidence path");
    HeptaEvidenceStore::open(&SqliteConfig::new_for_testing(absolute))
        .await
        .expect("evidence store")
}

fn authority(path: &std::path::Path, signing: &SigningKey) -> FinalUseAuthority {
    FinalUseAuthority::open_state_dir(
        path,
        "planner-grant-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority")
}

fn test_nonce(label: &str) -> [u8; 32] {
    digest(&format!("test-only-final-use-nonce:{label}")).into_array()
}

fn signed_final_use_grant(
    request: &GrantRequestV1,
    effect_binding: &EffectBindingV1,
    signing: &SigningKey,
    grant_id: &str,
    nonce: [u8; 32],
) -> SignedFinalUseGrant {
    let binding = final_use_binding_for_grant_request_v1(request, effect_binding).expect("binding");
    let now_ms = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("wall millis");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "planner-grant-issuer".to_string(),
        authority_epoch: 7,
        grant_id: grant_id.to_string(),
        nonce,
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 60_000,
    };
    SignedFinalUseGrant {
        signature: signing
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn plan_request(summary: OwnerSummaryV1, message: SignedMessage) -> GlobalControlHostRequestV1 {
    let objective = summary.objective_digest;
    let generation = summary.body_generation;
    let configuration = summary.configuration_digest;
    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let ndu = ndu_input(objective, generation, &owners);
    let fleet_summary = fleet_owner(objective, generation, configuration);
    let (fleet_message, _) = sign_owner_sequence(&fleet_summary, message.claims.sequence);
    let evaluation_policy_digest =
        canonical_ndu_planning_policy_digest(&ndu).expect("NDU policy digest");
    GlobalControlHostRequestV1 {
        snapshot_request: SnapshotRequestV1 {
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
        planning_request: PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 0,
            deadline_micros: 180,
            evaluation_policy_digest,
            resource_profile_digest: digest("overwritten-by-fleet"),
            candidates: vec![candidate("abstain", &owners), candidate("work", &owners)],
            resource_reservations: Vec::new(),
        },
        ndu_input: ndu,
        signed_owner_summaries: vec![
            SignedGlobalOwnerSummaryV1 { summary, message },
            SignedGlobalOwnerSummaryV1 {
                summary: fleet_summary,
                message: fleet_message,
            },
        ],
        fleet_allocation_id: "allocation:global-1".to_string(),
    }
}

#[tokio::test]
async fn producer_clock_epoch_cannot_control_host_planner_freshness() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[30; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let mut summary = evidence_owner(objective, generation, configuration);
    // An independent producer cannot know the supervisor process Instant epoch.
    // A hostile/future producer-local timestamp must therefore not enter the
    // planner's freshness arithmetic after authentication.
    summary.observed_at_micros = u64::MAX - 1;
    summary.expires_at_micros = u64::MAX;
    let producer_observed_at = summary.observed_at_micros;
    let (message, issuer) = sign_owner(&summary);

    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        fleet_state(),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let plan = host
        .plan(plan_request(summary, message))
        .await
        .expect("host-stamped global plan");
    let admitted = plan
        .snapshot
        .owner_summaries()
        .iter()
        .find(|owner| owner.owner_id.as_str() == "kernel.evidence")
        .expect("evidence owner");
    assert_ne!(admitted.observed_at_micros, producer_observed_at);
    assert!(admitted.expires_at_micros > admitted.observed_at_micros);
}

#[tokio::test]
async fn named_host_persists_plan_and_durable_owner_replay_survives_restart() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[31; 32]);

    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);

    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let result = host
        .plan(plan_request(summary.clone(), message))
        .await
        .expect("global plan");
    assert_eq!(
        result.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
    );
    assert_eq!(
        result.snapshot.snapshot_policy_digest(),
        host.policy().snapshot_policy_digest
    );
    assert!(result.snapshot.collected_at_micros() <= host.planner_now_micros().expect("clock"));
    assert_eq!(
        result.prepared.resource_profile_digest(),
        codex_hepta_control_plane::canonical_resource_profile_digest(&[
            codex_hepta_control_plane::ResourceReservationV1 {
                axis: id(FLEET_CPU_MILLIS_AXIS),
                endowment: q32(80),
                essential_floor: q32(10),
            },
            codex_hepta_control_plane::ResourceReservationV1 {
                axis: id(FLEET_MEMORY_MIB_AXIS),
                endowment: q32(32),
                essential_floor: q32(2),
            },
            codex_hepta_control_plane::ResourceReservationV1 {
                axis: id(FLEET_ACCELERATOR_MILLIS_AXIS),
                endowment: q32(10),
                essential_floor: q32(2),
            },
        ])
        .expect("host-owned resource profile")
    );
    assert_eq!(
        host.journal().selected_plan_digest(),
        Some(result.evaluation.plan.receipt_digest())
    );
    drop(host);

    let (same_message, issuer) = sign_owner(&summary);
    let mut reopened = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("reopened global host");
    assert!(matches!(
        reopened
            .plan(plan_request(summary, same_message))
            .await,
        Err(GlobalControlHostError::Evidence(_))
    ));
}

#[tokio::test]
async fn host_open_rejects_missing_required_owner_trust() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[36; 32]);
    let fleet = fleet_state();
    let (_, fleet_issuer) = sign_owner_sequence(
        &fleet_owner(
            digest("global-objective"),
            Generation::new(11).expect("generation"),
            digest("global-configuration"),
        ),
        1,
    );
    assert!(matches!(
        GlobalControlHostV1::open(
            evidence_store(&temporary.path().join("evidence")).await,
            &temporary.path().join("planner"),
            &[],
            authority(&temporary.path().join("authority"), &authority_signing),
            Arc::clone(&fleet),
            host_policy(),
            vec![GlobalOwnerTrustV1 {
                owner_id: id("runtime.fleet"),
                issuer: fleet_issuer,
            }],
        ),
        Err(GlobalControlHostError::MissingRequiredOwnerTrust(owner))
            if owner == id("kernel.evidence")
    ));
}

#[tokio::test]
async fn caller_cannot_omit_host_required_owner() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[38; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");

    let mut request = plan_request(summary, message);
    request
        .signed_owner_summaries
        .retain(|owner| owner.summary.owner_id.as_str() == "runtime.fleet");
    request.snapshot_request.required_owner_ids = vec![id("runtime.fleet")];

    assert!(matches!(
        host.plan(request).await,
        Err(GlobalControlHostError::Plane(
            GlobalPlaneError::OwnerSetMismatch
        ))
    ));
}

#[tokio::test]
async fn caller_cannot_replace_host_revocation_frontier() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[29; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        fleet_state(),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let mut request = plan_request(summary, message);
    request.snapshot_request.revocation_frontier_digest = digest("caller-stale-frontier");
    let plan = host.plan(request).await.expect("host-owned frontier");
    assert_eq!(
        plan.snapshot.revocation_frontier_digest(),
        digest("host-revocation-frontier")
    );
}

#[tokio::test]
async fn caller_cannot_relax_host_ndu_policy() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[37; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");

    let mut request = plan_request(summary, message);
    request.ndu_input.profile.required_organs.organ_ids = vec![id("runtime.fleet")];
    assert!(matches!(
        host.plan(request).await,
        Err(GlobalControlHostError::NduPolicyMismatch)
    ));
}

#[tokio::test]
async fn signed_fleet_owner_must_match_live_allocation_revision() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[39; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");

    let mut request = plan_request(summary, message);
    let mut stale_fleet = fleet_owner(objective, generation, configuration);
    stale_fleet.revision = Revision::new(6).expect("stale revision");
    let (stale_message, _) = sign_owner_sequence(&stale_fleet, 9);
    request.signed_owner_summaries[1] = SignedGlobalOwnerSummaryV1 {
        summary: stale_fleet,
        message: stale_message,
    };

    assert!(matches!(
        host.plan(request).await,
        Err(GlobalControlHostError::Plane(
            GlobalPlaneError::InvalidOwnerBinding
        ))
    ));
}

#[tokio::test]
async fn final_use_subject_must_match_host_pinned_fleet_principal() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[40; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");

    let beta_binding = EffectBindingV1 {
        subject_id: id("agent:beta"),
        destination_id: id("provider:effect"),
        scope_digest: digest("effect-scope"),
        effect_boundary_id: id("provider-dispatch"),
    };
    let mut request = plan_request(summary, message);
    let work = request
        .planning_request
        .candidates
        .iter_mut()
        .find(|candidate| candidate.candidate_id == id("work"))
        .expect("work candidate");
    work.effect_binding_digest = Some(
        canonical_effect_binding_digest_v1(&beta_binding).expect("beta effect binding digest"),
    );
    let plan = host.plan(request).await.expect("beta-bound advisory plan");
    let grant_request = plan
        .grant_requests
        .as_ref()
        .expect("grant requests")
        .requests()
        .first()
        .expect("effect request")
        .clone();
    let signed = signed_final_use_grant(
        &grant_request,
        &beta_binding,
        &authority_signing,
        "grant-beta",
        test_nonce("grant-beta"),
    );

    assert!(matches!(
        host.with_authorized_request(
            &plan,
            &signed,
            &grant_request,
            &beta_binding,
            || "must-not-run",
        ),
        Err(GlobalControlHostError::FleetSubjectMismatch)
    ));
}

#[tokio::test]
async fn revoked_planner_decision_cannot_reach_final_use() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[42; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let plan = host
        .plan(plan_request(summary, message))
        .await
        .expect("global plan");
    let request = plan
        .grant_requests
        .as_ref()
        .expect("grant requests")
        .requests()
        .first()
        .expect("effect request")
        .clone();
    let binding = effect_binding();
    let signed = signed_final_use_grant(
        &request,
        &binding,
        &authority_signing,
        "grant-revoked-plan",
        test_nonce("grant-revoked-plan"),
    );
    host.revoke_decision(digest("revoke-current-plan"), plan.evaluation.plan.receipt_digest())
        .expect("revoke decision");

    assert!(matches!(
        host.with_authorized_request(&plan, &signed, &request, &binding, || "must-not-run"),
        Err(GlobalControlHostError::PlanNotIssuedByCurrentHost)
            | Err(GlobalControlHostError::PlannerPlanNotCurrent)
    ));
}

#[tokio::test]
async fn pre_restart_plan_requires_replanning_before_final_use() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[43; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let plan = host
        .plan(plan_request(summary.clone(), message))
        .await
        .expect("global plan");
    let request = plan
        .grant_requests
        .as_ref()
        .expect("grant requests")
        .requests()
        .first()
        .expect("effect request")
        .clone();
    let binding = effect_binding();
    let signed = signed_final_use_grant(
        &request,
        &binding,
        &authority_signing,
        "grant-before-restart",
        test_nonce("grant-before-restart"),
    );
    drop(host);

    let (_, issuer) = sign_owner_sequence(&summary, 10);
    let reopened = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("reopened host");
    assert!(matches!(
        reopened.with_authorized_request(&plan, &signed, &request, &binding, || "must-not-run"),
        Err(GlobalControlHostError::PlanNotIssuedByCurrentHost)
    ));
}

#[tokio::test]
async fn named_host_releases_effect_only_inside_final_use_fence() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[41; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (message, issuer) = sign_owner(&summary);
    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("global host");
    let plan = host
        .plan(plan_request(summary, message))
        .await
        .expect("global plan");
    let request = plan
        .grant_requests
        .as_ref()
        .expect("grant requests")
        .requests()
        .first()
        .expect("effect request")
        .clone();
    let effect_binding = effect_binding();
    let signed = signed_final_use_grant(
        &request,
        &effect_binding,
        &authority_signing,
        "grant-1",
        test_nonce("grant-1"),
    );

    assert_eq!(
        host.with_authorized_request(
            &plan,
            &signed,
            &request,
            &effect_binding,
            || "released",
        )
        .expect("final-use dispatch"),
        "released"
    );
    assert!(matches!(
        host.with_authorized_request(
            &plan,
            &signed,
            &request,
            &effect_binding,
            || "must-not-run",
        ),
        Err(GlobalControlHostError::Authority(_))
    ));

    let current = fleet
        .read()
        .expect("fleet read lock")
        .get("allocation:global-1")
        .expect("current allocation")
        .clone();
    fleet
        .write()
        .expect("fleet write lock")
        .renew_or_revoke(
            1_001,
            &current.allocation_id,
            current.lease_generation,
            current.authority_epoch,
            &current.semantic_digest,
            LeaseDisposition::Revoke,
        )
        .expect("revoke allocation");
    let signed_after_revoke = signed_final_use_grant(
        &request,
        &effect_binding,
        &authority_signing,
        "grant-2",
        test_nonce("grant-2"),
    );
    assert!(matches!(
        host.with_authorized_request(
            &plan,
            &signed_after_revoke,
            &request,
            &effect_binding,
            || "must-not-run",
        ),
        Err(GlobalControlHostError::Plane(
            GlobalPlaneError::FleetAllocationRevoked
        ))
    ));
}

#[tokio::test]
#[ignore = "profiled separately by the Lane B exact-head workflow"]
async fn named_host_profile_emits_exact_runner_measurements() {
    const PLAN_ITERATIONS: u64 = 24;
    const REOPEN_ITERATIONS: usize = 6;

    let temporary = tempfile::tempdir().expect("tempdir");
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[61; 32]);
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = Generation::new(11).expect("generation");
    let summary = evidence_owner(objective, generation, configuration);
    let (_, issuer) = sign_owner_sequence(&summary, 1);

    let fleet = fleet_state();
    let mut host = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("profile host");

    let mut plan_micros = Vec::with_capacity(PLAN_ITERATIONS as usize);
    for sequence in 1..=PLAN_ITERATIONS {
        let (message, _) = sign_owner_sequence(&summary, sequence);
        let request = plan_request(summary.clone(), message);
        let started = Instant::now();
        host.plan(request)
            .await
            .expect("profile plan");
        plan_micros.push(elapsed_micros(started));
    }
    drop(host);

    let mut reopen_micros = Vec::with_capacity(REOPEN_ITERATIONS);
    for _ in 0..REOPEN_ITERATIONS {
        let (_, issuer) = sign_owner_sequence(&summary, PLAN_ITERATIONS + 1);
        let started = Instant::now();
        let reopened = GlobalControlHostV1::open(
            evidence_store(&evidence_path).await,
            &planner_path,
            &[],
            authority(&authority_path, &authority_signing),
            Arc::clone(&fleet),
            host_policy(),
            owner_trusts(issuer),
        )
        .expect("profile reopen");
        reopen_micros.push(elapsed_micros(started));
        drop(reopened);
    }

    let (replayed_message, issuer) = sign_owner_sequence(&summary, PLAN_ITERATIONS);
    let mut reopened = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        Arc::clone(&fleet),
        host_policy(),
        owner_trusts(issuer),
    )
    .expect("fault probe host");
    let replay_rejected = matches!(
        reopened
            .plan(plan_request(summary, replayed_message))
            .await,
        Err(GlobalControlHostError::Evidence(_))
    );
    assert!(replay_rejected);

    plan_micros.sort_unstable();
    reopen_micros.sort_unstable();
    println!(
        concat!(
            "HEPTA_SUPERVISOR_GLOBAL_CONTROL_PROFILE ",
            "{{\"schema\":\"hepta.supervisor-global-control-profile.v1\",",
            "\"sha\":\"{}\",",
            "\"runner_os\":\"{}\",",
            "\"runner_arch\":\"{}\",",
            "\"plan\":{{\"iterations\":{},\"p50_us\":{},\"p95_us\":{},\"p99_us\":{},\"max_us\":{}}},",
            "\"reopen\":{{\"iterations\":{},\"p50_us\":{},\"p95_us\":{},\"max_us\":{}}},",
            "\"faults\":{{\"durable_replay_rejected\":{}}}}}"
        ),
        std::env::var("HEPTA_PROFILE_SHA").unwrap_or_else(|_| "local".to_string()),
        std::env::var("RUNNER_OS").unwrap_or_else(|_| std::env::consts::OS.to_string()),
        std::env::var("RUNNER_ARCH").unwrap_or_else(|_| std::env::consts::ARCH.to_string()),
        PLAN_ITERATIONS,
        percentile(&plan_micros, 50),
        percentile(&plan_micros, 95),
        percentile(&plan_micros, 99),
        plan_micros.last().copied().unwrap_or(0),
        REOPEN_ITERATIONS,
        percentile(&reopen_micros, 50),
        percentile(&reopen_micros, 95),
        reopen_micros.last().copied().unwrap_or(0),
        replay_rejected,
    );
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let numerator = percentile.saturating_mul(values.len().saturating_sub(1));
    let index = numerator.div_ceil(100);
    values[index.min(values.len() - 1)]
}
