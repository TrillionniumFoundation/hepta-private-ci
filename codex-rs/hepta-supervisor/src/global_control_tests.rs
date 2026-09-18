use std::collections::BTreeSet;
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
use codex_hepta_control_plane::FLEET_ACCELERATOR_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_CPU_MILLIS_AXIS;
use codex_hepta_control_plane::FLEET_MEMORY_MIB_AXIS;
use codex_hepta_control_plane::FleetEssentialFloorsV1;
use codex_hepta_control_plane::GrantRequestV1;
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
        observed_at_micros: 95,
        expires_at_micros: 195,
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
    let signing = SigningKey::from_bytes(&[21; 32]);
    let claims = SignedMessageClaims {
        issuer_id: id("issuer:evidence"),
        key_epoch: Generation::new(4).expect("key epoch"),
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
            key_epoch: Generation::new(4).expect("key epoch"),
            verifying_key: signing.verifying_key(),
            revoked: false,
        },
    )
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

fn plan_request(summary: OwnerSummaryV1, message: SignedMessage) -> GlobalControlHostRequestV1 {
    let objective = summary.objective_digest;
    let generation = summary.body_generation;
    let configuration = summary.configuration_digest;
    let owners = vec![id("kernel.evidence"), id("runtime.fleet")];
    let ndu = ndu_input(objective, generation, &owners);
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
            candidates: vec![
                candidate("abstain", &owners),
                candidate("work", &owners),
            ],
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

    let mut host = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        vec![GlobalOwnerTrustV1 {
            owner_id: id("kernel.evidence"),
            issuer,
        }],
    )
    .expect("global host");
    let result = host
        .plan(&fleet_ledger(), plan_request(summary.clone(), message))
        .await
        .expect("global plan");
    assert_eq!(
        result.evaluation.plan.chosen_candidate_id(),
        Some(&id("work"))
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
        vec![GlobalOwnerTrustV1 {
            owner_id: id("kernel.evidence"),
            issuer,
        }],
    )
    .expect("reopened global host");
    assert!(matches!(
        reopened
            .plan(&fleet_ledger(), plan_request(summary, same_message))
            .await,
        Err(GlobalControlHostError::Evidence(_))
    ));
}

#[tokio::test]
async fn named_host_releases_effect_only_inside_final_use_fence() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let authority_signing = SigningKey::from_bytes(&[41; 32]);
    let host = GlobalControlHostV1::open(
        evidence_store(&temporary.path().join("evidence")).await,
        &temporary.path().join("planner"),
        &[],
        authority(&temporary.path().join("authority"), &authority_signing),
        Vec::new(),
    )
    .expect("global host");
    let request = GrantRequestV1 {
        operation_id: id("operation:send"),
        candidate_id: id("candidate:send"),
        plan_digest: digest("plan"),
        final_payload_digest: digest("payload"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        revocation_frontier_digest: digest("revocation-frontier"),
        expires_at_micros: 10_000,
    };
    let subject = id("agent:alpha");
    let destination = id("provider:effect");
    let scope = digest("effect-scope");
    let binding =
        final_use_binding_for_grant_request_v1(&request, &subject, &destination, scope)
            .expect("binding");
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
        grant_id: "grant-1".to_string(),
        nonce: [51; 32],
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 60_000,
    };
    let signed = SignedFinalUseGrant {
        signature: authority_signing
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };

    assert_eq!(
        host.with_authorized_request(
            &signed,
            &request,
            &subject,
            &destination,
            scope,
            || "released",
        )
        .expect("final-use dispatch"),
        "released"
    );
    assert!(matches!(
        host.with_authorized_request(
            &signed,
            &request,
            &subject,
            &destination,
            scope,
            || "must-not-run",
        ),
        Err(GlobalControlHostError::Authority(_))
    ));
}


#[tokio::test]
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

    let mut host = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        vec![GlobalOwnerTrustV1 {
            owner_id: id("kernel.evidence"),
            issuer,
        }],
    )
    .expect("profile host");

    let mut plan_micros = Vec::with_capacity(PLAN_ITERATIONS as usize);
    let mut last_message = None;
    for sequence in 1..=PLAN_ITERATIONS {
        let (message, _) = sign_owner_sequence(&summary, sequence);
        let request = plan_request(summary.clone(), message.clone());
        let started = Instant::now();
        host.plan(&fleet_ledger(), request)
            .await
            .expect("profile plan");
        plan_micros.push(elapsed_micros(started));
        last_message = Some(message);
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
            vec![GlobalOwnerTrustV1 {
                owner_id: id("kernel.evidence"),
                issuer,
            }],
        )
        .expect("profile reopen");
        reopen_micros.push(elapsed_micros(started));
        drop(reopened);
    }

    let (_, issuer) = sign_owner_sequence(&summary, PLAN_ITERATIONS + 1);
    let mut reopened = GlobalControlHostV1::open(
        evidence_store(&evidence_path).await,
        &planner_path,
        &[],
        authority(&authority_path, &authority_signing),
        vec![GlobalOwnerTrustV1 {
            owner_id: id("kernel.evidence"),
            issuer,
        }],
    )
    .expect("fault probe host");
    let replay_rejected = matches!(
        reopened
            .plan(
                &fleet_ledger(),
                plan_request(summary, last_message.expect("profile emitted message")),
            )
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
        std::env::var("GITHUB_SHA").unwrap_or_else(|_| "local".to_string()),
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
