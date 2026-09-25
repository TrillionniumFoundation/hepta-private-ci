#![cfg(unix)]

use std::collections::BTreeSet;
use std::fmt::Debug;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_control_plane::AuthorityBridgeError;
use codex_hepta_control_plane::FLEET_ACCELERATOR_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_CPU_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_MEMORY_MIB_AXIS;
use codex_hepta_control_plane::FleetEssentialFloorsV1;
use codex_hepta_control_plane::NduPlanningInputV1;
use codex_hepta_control_plane::OwnerReadinessV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlanCandidateV1;
use codex_hepta_control_plane::PlannerAxisValueV1;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::canonical_ndu_planning_policy_digest;
use codex_hepta_control_plane::final_use_binding_for_grant_request_v1;
use codex_hepta_control_plane::owner_summary_payload_digest_v1;
use codex_hepta_control_plane::owner_summary_scope_digest_v1;
use codex_hepta_evidence::HeptaEvidenceStore;
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
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::GlobalControlHostError;
use super::GlobalControlHostRequestV1;
use super::GlobalControlHostV1;
use super::GlobalOwnerTrustV1;
use super::SignedGlobalOwnerSummaryV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

async fn must_async<T, E: Debug>(future: impl std::future::Future<Output = Result<T, E>>) -> T {
    must(future.await)
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

fn evidence_owner(
    objective: Digest32,
    generation: Generation,
    configuration: Digest32,
) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id("kernel.evidence"),
        revision: must(Revision::new(generation.get())),
        objective_digest: objective,
        body_generation: generation,
        configuration_digest: configuration,
        observed_at_micros: 95,
        expires_at_micros: 195,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest(&format!("evidence-frontier:{}", generation.get())),
        support_digest: digest(&format!("evidence-support:{}", generation.get())),
    }
}

fn sign_owner(summary: &OwnerSummaryV1, sequence: u64) -> (SignedMessage, IssuerRegistration) {
    let signing = SigningKey::from_bytes(&[21; 32]);
    let claims = SignedMessageClaims {
        issuer_id: id("issuer:evidence"),
        key_epoch: must(Generation::new(4)),
        message_id: id(&format!("message:evidence:{sequence}")),
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
            issuer_id: id("issuer:evidence"),
            key_epoch: must(Generation::new(4)),
            verifying_key: signing.verifying_key(),
            revoked: false,
        },
    )
}

fn fleet_ledger() -> LeaseLedger {
    let mut ledger = LeaseLedger::new();
    must(ledger.admit_host(HostObservation {
        host_id: "host-a".to_string(),
        failure_domain_id: "rack-a".to_string(),
        generation: 3,
        observed_at_ms: 1,
        valid_until_ms: u64::MAX,
        capacity: Resources {
            cpu_millis: 100,
            memory_bytes: 64 * 1024 * 1024,
            accelerator_millis: 20,
        },
    }));
    must(ledger.issue(
        2,
        AllocationGrant {
            allocation_id: "allocation:global-1".to_string(),
            request_id: "request:global-1".to_string(),
            principal_id: "agent:alpha".to_string(),
            host_id: "host-a".to_string(),
            failure_domain_id: "rack-a".to_string(),
            host_generation: 3,
            authority_epoch: 7,
            lease_generation: 5,
            expires_at_ms: u64::MAX - 1,
            resources: Resources {
                cpu_millis: 80,
                memory_bytes: 32 * 1024 * 1024,
                accelerator_millis: 10,
            },
            semantic_digest: digest("fleet-allocation").to_string(),
            revoked: false,
        },
    ));
    ledger
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
    let axis = id("global-utility");
    let profile = UtilityProfile {
        profile_id: id("global-control-profile"),
        axis_registry_digest: digest("global-control-axis-registry"),
        normalization_manifest_digest: digest("global-control-normalization"),
        dimensions: vec![(axis.clone(), AxisDirection::Maximize)],
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
        for owner in owners {
            input.contributions.contributions.push(UtilityContribution {
                candidate_id: id(candidate_id),
                organ_id: owner.clone(),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: axis.clone(),
                    value: if candidate_id == "work" {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: vec![],
                resource: vec![],
                uncertainty: vec![AxisValue {
                    axis: axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest(&format!("{candidate_id}:{}", owner.as_str())),
            });
        }
    }
    input
}

fn request(generation_value: u64, sequence: u64) -> GlobalControlHostRequestV1 {
    let objective = digest("global-objective");
    let configuration = digest("global-configuration");
    let generation = must(Generation::new(generation_value));
    let summary = evidence_owner(objective, generation, configuration);
    let (message, _issuer) = sign_owner(&summary, sequence);
    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let ndu = ndu_input(objective, generation, &owners);
    GlobalControlHostRequestV1 {
        snapshot_request: SnapshotRequestV1 {
            objective_digest: objective,
            body_generation: generation,
            configuration_digest: configuration,
            revocation_frontier_digest: digest(&format!("revocation:{generation_value}")),
            snapshot_policy_digest: digest("global-snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 20,
            expires_at_micros: 200,
            required_owner_ids: owners.clone(),
        },
        planning_request: PlanningRequestV1 {
            plan_id: id(&format!("global-plan:{generation_value}")),
            now_micros: 0,
            deadline_micros: 180,
            evaluation_policy_digest: must(canonical_ndu_planning_policy_digest(&ndu)),
            resource_profile_digest: digest("overwritten-by-fleet"),
            candidates: vec![candidate("abstain", &owners), candidate("work", &owners)],
            resource_reservations: Vec::new(),
        },
        ndu_input: ndu,
        signed_owner_summaries: vec![SignedGlobalOwnerSummaryV1 { summary, message }],
        fleet_allocation_id: "allocation:global-1".to_string(),
        fleet_principal_id: "agent:alpha".to_string(),
        fleet_floors: FleetEssentialFloorsV1 {
            cpu_millis: 10,
            memory_bytes: 2 * 1024 * 1024,
            accelerator_millis: 2,
        },
        now_micros: 100,
    }
}

async fn evidence_store(path: &std::path::Path) -> HeptaEvidenceStore {
    must(std::fs::create_dir_all(path));
    let absolute = must(AbsolutePathBuf::from_absolute_path(path));
    must_async(HeptaEvidenceStore::open(&SqliteConfig::new_for_testing(
        absolute,
    )))
    .await
}

fn authority(path: &std::path::Path, signing: &SigningKey) -> FinalUseAuthority {
    must(FinalUseAuthority::open_state_dir(
        path,
        "planner-grant-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    ))
}

fn owner_trust() -> Vec<GlobalOwnerTrustV1> {
    let summary = evidence_owner(
        digest("global-objective"),
        must(Generation::new(11)),
        digest("global-configuration"),
    );
    let (_message, issuer) = sign_owner(&summary, 1);
    vec![GlobalOwnerTrustV1 {
        owner_id: id("kernel.evidence"),
        issuer,
    }]
}

#[tokio::test]
async fn committed_plan_survives_ack_loss_and_replay_is_rejected_after_restart() {
    let temporary = must(tempfile::tempdir());
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[31; 32]);

    let mut host = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    let plan = must_async(host.plan(&fleet_ledger(), request(11, 1))).await;
    let selected = plan.evaluation.plan.receipt_digest();
    assert_eq!(host.journal().selected_plan_digest(), Some(selected));
    // Lose the response after durable commit.
    drop(host);

    let mut reopened = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    assert_eq!(reopened.journal().selected_plan_digest(), Some(selected));
    assert_eq!(
        reopened.committed_plan_receipt(&id("global-plan:11")),
        Some(selected)
    );
    match reopened.plan(&fleet_ledger(), request(11, 1)).await {
        Err(GlobalControlHostError::OperationAlreadyCommitted(actual)) => {
            assert_eq!(actual, selected);
        }
        Err(error) => panic!("unexpected retry error: {error:?}"),
        Ok(_) => panic!("committed operation unexpectedly re-executed"),
    }
}

#[tokio::test]
async fn restart_accepts_a_new_generation_without_resurrecting_the_old_selection() {
    let temporary = must(tempfile::tempdir());
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[41; 32]);

    let mut host = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    let old = must_async(host.plan(&fleet_ledger(), request(11, 1))).await;
    let old_digest = old.evaluation.plan.receipt_digest();
    drop(host);

    let mut reopened = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    let new = must_async(reopened.plan(&fleet_ledger(), request(12, 2))).await;
    let new_digest = new.evaluation.plan.receipt_digest();
    assert_ne!(old_digest, new_digest);
    assert_eq!(reopened.journal().selected_plan_digest(), Some(new_digest));
}

#[tokio::test]
async fn host_revocation_is_durable_and_blocks_reselection() {
    let temporary = must(tempfile::tempdir());
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[51; 32]);

    let mut host = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    let plan = must_async(host.plan(&fleet_ledger(), request(11, 1))).await;
    let decision = plan.evaluation.plan.receipt_digest();
    must(host.revoke_decision(digest("revocation:decision"), decision));
    assert_eq!(host.journal().selected_plan_digest(), None);
    drop(host);

    let reopened = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[decision],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    assert_eq!(reopened.journal().selected_plan_digest(), None);
}

#[tokio::test]
async fn planner_expiry_and_current_final_use_revocation_block_local_dispatch_boundary() {
    let temporary = must(tempfile::tempdir());
    let evidence_path = temporary.path().join("evidence");
    let planner_path = temporary.path().join("planner");
    let authority_path = temporary.path().join("authority");
    let authority_signing = SigningKey::from_bytes(&[61; 32]);

    let mut host = must(GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        owner_trust(),
    ));
    let plan = must_async(host.plan(&fleet_ledger(), request(11, 1))).await;
    let requests = match plan.grant_requests.as_ref() {
        Some(requests) => requests,
        None => panic!("work plan must produce one grant request"),
    };
    let grant_request = match requests.requests().first() {
        Some(request) => request,
        None => panic!("work plan grant request is missing"),
    };
    let subject = id("agent:alpha");
    let destination = id("worker:alpha");
    let scope = digest("global-control-effect-scope");
    let binding = must(final_use_binding_for_grant_request_v1(
        grant_request,
        &subject,
        &destination,
        scope,
    ));
    let now_ms = must(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_millis())
            .map_err(|error| error.to_string()),
    );
    let now_ms = must(u64::try_from(now_ms));
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "planner-grant-issuer".to_string(),
        authority_epoch: 7,
        grant_id: "global-control-grant".to_string(),
        nonce: [9; 32],
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: must(now_ms.checked_add(60_000).ok_or("time overflow")),
    };
    let signature = authority_signing
        .sign(&must(grant.signing_bytes()))
        .to_bytes();
    let signed = SignedFinalUseGrant {
        grant,
        signature: signature.to_vec(),
    };

    let mut expired_entered = false;
    let expired = host.with_authorized_request(
        &signed,
        grant_request,
        grant_request.expires_at_micros,
        &subject,
        &destination,
        scope,
        || expired_entered = true,
    );
    assert!(matches!(
        expired,
        Err(GlobalControlHostError::Authority(
            AuthorityBridgeError::PlannerRequestExpired
        ))
    ));
    assert!(!expired_entered);

    let mut revoked = BTreeSet::new();
    revoked.insert("global-control-grant".to_string());
    must(host.apply_final_use_revocations(FinalUseRevocations {
        authority_epoch: 7,
        revision: 2,
        revoked_grant_ids: revoked,
    }));

    let mut entered = false;
    let result = host.with_authorized_request(
        &signed,
        grant_request,
        grant_request.expires_at_micros - 1,
        &subject,
        &destination,
        scope,
        || entered = true,
    );
    assert!(result.is_err());
    assert!(!entered);
}
