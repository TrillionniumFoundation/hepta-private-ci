use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::RuntimeStateStatus;
#[cfg(unix)]
use crate::{
    RuntimeTopologyApplyRequestV1, RuntimeTopologySuccessorV1,
    runtime_topology_final_use_binding_v1, runtime_topology_recovery_final_use_binding_v1,
};

#[derive(Debug)]
struct ObservedAdapter(Arc<AtomicUsize>);

impl RuntimeStateAdapter for ObservedAdapter {
    fn status(&self) -> RuntimeStateStatus {
        self.0.fetch_add(1, Ordering::SeqCst);
        RuntimeStateStatus {
            adapter: "observed-test-adapter",
            schema_version: 5,
            outcome_generation: 3,
            preference_generation: 4,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 9,
            integrity_binding_present: true,
            integrity_verification: "test-only",
            open_mode: "read-only-test",
        }
    }
}

#[test]
fn live_status_request_traverses_the_initialized_graph() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-organ-request"))?;
    let runtime =
        crate::HeptaRuntime::from_adapter(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
    // Opening a host must not pretend to have observed a request or outcome.
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let report: serde_json::Value = serde_json::from_slice(&runtime.status_json()?)?;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(report["state"]["runtime_snapshot_generation"], 9);
    assert_eq!(
        report["authority"],
        serde_json::to_value(RuntimeAuthorityStatus::default())?
    );
    assert_eq!(runtime.clone().status_json()?, runtime.status_json()?);
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    Ok(())
}

#[test]
fn busy_or_stopped_hosts_never_bypass_dispatch() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-organ-stopped"))?;
    let organs = RuntimeOrgans::new(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
    let mut guard = organs
        .host
        .lock()
        .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
    assert!(organs.status_json().is_err());
    let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
    host.host.stop_all()?;
    drop(guard);
    assert!(organs.status_json().is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn status_consumer_checks_the_complete_hierarchy_without_direct_adapter_fallback() -> Result<()> {
    for case in 0..5 {
        let calls = Arc::new(AtomicUsize::new(0));
        let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-hierarchy-route"))?;
        let organs = RuntimeOrgans::new(root, Arc::new(ObservedAdapter(Arc::clone(&calls))));
        let original = {
            let mut guard = organs
                .host
                .lock()
                .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
            let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
            let original = host.route.clone();
            match case {
                0 => host.route.cns = StableId::new("other.cns")?,
                1 => host.route.source.system = StableId::new("other.system")?,
                2 => host.route.source.driver = StableId::new("other.driver")?,
                3 => host.route.targets[0].driver = StableId::new("other.target.driver")?,
                4 => host.route.generation = host.route.generation.next()?,
                _ => unreachable!(),
            }
            original
        };
        assert!(organs.status_json().is_err(), "case {case}");
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        {
            let mut guard = organs
                .host
                .lock()
                .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
            let host = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
            host.route = original;
        }
        let report: serde_json::Value = serde_json::from_slice(&organs.status_json()?)?;
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(report["state"]["runtime_snapshot_generation"], 9);
    }
    Ok(())
}

#[cfg(unix)]
fn governed_topology_for_runtime(
    label: &str,
    current: &crate::RuntimeTopologySnapshotV1,
    successor: &crate::RuntimeTopologySnapshotV1,
) -> (codex_hepta_plasticity::GovernedTopologyProposalV1, StableId) {
    use codex_hepta_plasticity::{
        ProposalWindowV2, TopologyCandidateKindV2, TopologyChangeV2, TopologyOperationV2,
        TopologyProposalRequestV2, admit_governed_topology_v1, build_writer_handoff_plan_v1,
        propose_topology_v2,
    };

    let migration = Digest32::of_bytes(b"runtime-topology-migration");
    let rollback = Digest32::of_bytes(b"runtime-topology-rollback");
    let handoff = build_writer_handoff_plan_v1(
        StableId::new("runtime.status.adapter").expect("module id"),
        StableId::new(format!("runtime.owner.generation-{}", current.generation().get()))
            .expect("from owner"),
        StableId::new(format!("runtime.owner.generation-{}", successor.generation().get()))
            .expect("to owner"),
        current.generation().get(),
        successor.generation().get(),
        current.hierarchy_digest(),
        migration,
        rollback,
        Digest32::of_bytes(b"runtime-topology-ack-contract"),
    )
    .expect("writer handoff");
    let selected = Digest32::of_bytes(b"runtime-selected-artifact");
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: StableId::new(format!("topology:runtime:{label}")).expect("proposal id"),
        proposer_id: StableId::new("learning.plasticity").expect("proposer"),
        evaluator_id: StableId::new("learning.eval").expect("evaluator"),
        selected_artifact_digest: selected,
        window: ProposalWindowV2 {
            window_id: StableId::new(format!("window:runtime:{label}")).expect("window"),
            window_digest: Digest32::of_bytes(format!("runtime-window:{label}").as_bytes()),
        },
        baseline_generation: current.generation(),
        candidate_generation: successor.generation(),
        evaluation_digest: Digest32::of_bytes(b"runtime-topology-evaluation"),
        rollback_predecessor_digest: selected,
        changes: vec![TopologyChangeV2 {
            module_id: handoff.module_id.clone(),
            operation: TopologyOperationV2::Replace,
            predecessor_digest: Some(current.hierarchy_digest()),
            candidate_digest: Some(successor.hierarchy_digest()),
            capability_typing_digest: Digest32::of_bytes(b"runtime-capability-typing"),
            compatibility_plan_digest: Digest32::of_bytes(b"runtime-compatibility"),
            lesion_ablation_digest: Digest32::of_bytes(b"runtime-lesion"),
            resource_review_digest: Digest32::of_bytes(b"runtime-resource-review"),
            security_review_digest: Digest32::of_bytes(b"runtime-security-review"),
            migration_digest: migration,
            rollback_digest: rollback,
            writer_handoff_digest: handoff.plan_digest,
            evidence_digest: Digest32::of_bytes(b"runtime-topology-evidence"),
        }],
    })
    .expect("topology proposal");
    let candidate_id = proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
        .expect("update candidate")
        .candidate_id
        .clone();
    let governed = admit_governed_topology_v1(
        proposal,
        vec![handoff],
        Digest32::of_bytes(b"runtime-source-authentication"),
        Digest32::of_bytes(b"runtime-evaluation-authentication"),
    )
    .expect("governed topology");
    (governed, candidate_id)
}

#[cfg(unix)]
fn final_use_authority_and_grant(
    binding: codex_hepta_contracts::FinalUseBinding,
    grant_id: &str,
    nonce: [u8; 32],
) -> (
    tempfile::TempDir,
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::SignedFinalUseGrant,
) {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::{SystemTime, UNIX_EPOCH};

    use codex_hepta_contracts::{
        FinalUseAuthority, FinalUseGrant, FinalUseRevocations, SignedFinalUseGrant,
    };
    use ed25519_dalek::{Signer, SigningKey};

    let directory = tempfile::tempdir().expect("authority directory");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority directory");
    let key = SigningKey::from_bytes(&[0x55; 32]);
    let signer_id = "runtime-topology-authority".to_string();
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        signer_id.clone(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_millis(),
    )
    .expect("millisecond clock");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id,
        authority_epoch: 1,
        grant_id: grant_id.to_string(),
        nonce,
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now.checked_add(60_000).expect("grant expiry"),
    };
    let signature = key
        .sign(&grant.signing_bytes().expect("grant signing bytes"))
        .to_bytes()
        .to_vec();
    (
        directory,
        authority,
        SignedFinalUseGrant { grant, signature },
    )
}

#[cfg(unix)]
fn runtime_canary_observer() -> (
    codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    ed25519_dalek::SigningKey,
    codex_hepta_learning_ledger::AuthenticatedPrincipalV1,
) {
    use codex_hepta_learning_ledger::{
        AuthenticatedPrincipalV1, LearningEvidenceRoleV1, LearningEvidenceTrustV1,
        LearningEvidenceVerifierV1, TrustedLearningSignerV1,
    };

    let key = ed25519_dalek::SigningKey::from_bytes(&[0x66; 32]);
    let scope = Digest32::of_bytes(b"runtime-topology-canary-scope");
    let objective = Digest32::of_bytes(b"runtime-topology-canary-objective");
    let principal = AuthenticatedPrincipalV1 {
        principal_id: StableId::new("observer:runtime-topology-canary").expect("observer"),
        credential_chain_digest: Digest32::of_bytes(b"runtime-topology-canary-credential"),
        signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
        scope_digest: scope,
        authority_epoch: 9,
        authenticated_at: 10,
        expires_at: 100,
    };
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 9,
        signers: vec![TrustedLearningSignerV1 {
            principal: principal.clone(),
            controller_id: StableId::new("controller:runtime-topology-canary")
                .expect("controller"),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Observer],
            revoked_at: None,
        }],
    })
    .expect("runtime canary verifier");
    (verifier, key, principal)
}

#[cfg(unix)]
fn sign_runtime_canary_observation(
    verifier: &codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    key: &ed25519_dalek::SigningKey,
    principal: &codex_hepta_learning_ledger::AuthenticatedPrincipalV1,
    plan_digest: Digest32,
    observation: &codex_hepta_plasticity::StructuralCanaryObservationV1,
) -> codex_hepta_learning_ledger::SignedLearningEvidenceV1 {
    use codex_hepta_intelligence::structural_canary_observation_signing_payload_v1;
    use codex_hepta_learning_ledger::{LearningEvidenceRoleV1, SignedLearningEvidenceV1};
    use ed25519_dalek::Signer;

    let payload =
        structural_canary_observation_signing_payload_v1(plan_digest, observation)
            .expect("runtime canary signing payload");
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("runtime-canary:evidence:{}", observation.sequence))
            .expect("evidence id"),
        principal_id: principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: Digest32::of_bytes(b"runtime-topology-canary-objective"),
        authority_epoch: principal.authority_epoch,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[cfg(unix)]
#[test]
fn governed_topology_requires_final_use_and_replaces_the_live_cns_generation() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(
        std::env::temp_dir().join(format!("hepta-topology-execution-{}", std::process::id())),
    )?;
    let state: Arc<dyn RuntimeStateAdapter> = Arc::new(ObservedAdapter(Arc::clone(&calls)));
    let organs = RuntimeOrgans::new(root.clone(), Arc::clone(&state));
    let current = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;

    let next = build_host_generation(root, state, Generation::new(2)?)?;
    let successor = RuntimeTopologySuccessorV1::new(next.host, next.route)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let successor_snapshot = successor.snapshot();
    let (governed, candidate_id) =
        governed_topology_for_runtime("apply", &current, &successor_snapshot);
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:accepted-topology")?,
        successor,
    };
    let binding = runtime_topology_final_use_binding_v1(&current, &request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_authority_directory, authority, signed) =
        final_use_authority_and_grant(binding, "grant:runtime-topology:1", [0x11; 32]);

    let receipt = organs
        .apply_governed_topology(&authority, &signed, request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(receipt.predecessor_generation, Generation::new(1)?);
    assert_eq!(receipt.successor_generation, Generation::new(2)?);
    assert_eq!(
        receipt.successor_hierarchy_digest,
        successor_snapshot.hierarchy_digest()
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);

    let after = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(after.generation(), Generation::new(2)?);
    assert_eq!(
        after.hierarchy_digest(),
        successor_snapshot.hierarchy_digest()
    );
    let report: serde_json::Value = serde_json::from_slice(&organs.status_json()?)?;
    assert_eq!(report["status"], "ready");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[cfg(unix)]
#[test]
fn revoked_final_use_never_mutates_the_live_topology() -> Result<()> {
    use std::collections::BTreeSet;

    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(
        std::env::temp_dir().join(format!("hepta-topology-revoked-{}", std::process::id())),
    )?;
    let state: Arc<dyn RuntimeStateAdapter> = Arc::new(ObservedAdapter(Arc::clone(&calls)));
    let organs = RuntimeOrgans::new(root.clone(), Arc::clone(&state));
    let current = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let next = build_host_generation(root, state, Generation::new(2)?)?;
    let successor = RuntimeTopologySuccessorV1::new(next.host, next.route)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let successor_snapshot = successor.snapshot();
    let (governed, candidate_id) =
        governed_topology_for_runtime("revoked", &current, &successor_snapshot);
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:revoked-topology")?,
        successor,
    };
    let binding = runtime_topology_final_use_binding_v1(&current, &request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_authority_directory, authority, signed) =
        final_use_authority_and_grant(binding, "grant:runtime-topology:revoked", [0x22; 32]);
    authority.update_revocations(codex_hepta_contracts::FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: BTreeSet::from(["grant:runtime-topology:revoked".to_string()]),
    })?;

    assert!(matches!(
        organs.apply_governed_topology(&authority, &signed, request),
        Err(crate::RuntimeTopologyExecutionError::FinalUse(
            codex_hepta_contracts::FinalUseError::Revoked
        ))
    ));
    assert_eq!(
        organs
            .topology_snapshot()
            .map_err(|error| anyhow::anyhow!("{error}"))?,
        current
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    Ok(())
}


#[cfg(unix)]
#[test]
fn authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics(
) -> Result<()> {
    use codex_hepta_intelligence::observe_authenticated_structural_canary_v1;
    use codex_hepta_plasticity::{
        DurableTopologyProposalRegistryV1, StructuralCanaryControllerV1,
        StructuralCanaryObservationV1, StructuralCanaryStateV1, build_structural_canary_plan_v1,
    };

    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join(format!(
        "hepta-topology-real-canary-{}",
        std::process::id()
    )))?;
    let state: Arc<dyn RuntimeStateAdapter> = Arc::new(ObservedAdapter(Arc::clone(&calls)));
    let organs = RuntimeOrgans::new(root.clone(), Arc::clone(&state));
    let baseline = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;

    let next = build_host_generation(root.clone(), Arc::clone(&state), Generation::new(2)?)?;
    let successor = RuntimeTopologySuccessorV1::new(next.host, next.route)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let successor_snapshot = successor.snapshot();
    let (governed, candidate_id) =
        governed_topology_for_runtime("canary-apply", &baseline, &successor_snapshot);

    // Bind the canary controller to the exact durable governed proposal before execution.
    let mut registry = DurableTopologyProposalRegistryV1::bootstrap_empty(
        tempfile::tempfile()?,
        Digest32::of_bytes(b"runtime-topology-canary-registry"),
        1,
        8,
    )?;
    let append = registry.append(Digest32::ZERO, governed.clone())?;
    assert_eq!(append.sequence, 1);
    let plan = build_structural_canary_plan_v1(
        &registry,
        &governed.proposal.proposal_id,
        candidate_id.clone(),
        Digest32::of_bytes(b"runtime-topology-baseline-health"),
        2,
        0,
        1,
    )?;
    let mut controller = StructuralCanaryControllerV1::new(plan)?;

    let apply_request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:runtime-canary-apply")?,
        successor,
    };
    let apply_binding = runtime_topology_final_use_binding_v1(&baseline, &apply_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_apply_dir, apply_authority, apply_grant) =
        final_use_authority_and_grant(apply_binding, "grant:runtime-canary:apply", [0x31; 32]);
    let apply_receipt = organs
        .apply_governed_topology(&apply_authority, &apply_grant, apply_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(apply_receipt.predecessor_generation, Generation::new(1)?);
    assert_eq!(apply_receipt.successor_generation, Generation::new(2)?);

    // Force a real live-host failure after cutover, rather than synthesizing a boolean-only fault.
    {
        let mut guard = organs
            .host
            .lock()
            .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
        let live = guard
            .as_mut()
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        live.host.stop_all()?;
    }
    assert!(organs.status_json().is_err());

    // Rollback is an authorized new transition (generation 2 -> 3), not time travel.
    let failed = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let rollback_host =
        build_host_generation(root, Arc::clone(&state), Generation::new(3)?)?;
    let rollback_successor = RuntimeTopologySuccessorV1::new(
        rollback_host.host,
        rollback_host.route,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let rollback_snapshot = rollback_successor.snapshot();
    let (rollback_governed, rollback_candidate_id) =
        governed_topology_for_runtime("canary-rollback", &failed, &rollback_snapshot);
    let rollback_request = RuntimeTopologyApplyRequestV1 {
        governed: rollback_governed,
        candidate_id: rollback_candidate_id,
        accepted_subject_id: StableId::new("operator:runtime-canary-rollback")?,
        successor: rollback_successor,
    };
    let rollback_binding =
        runtime_topology_recovery_final_use_binding_v1(&failed, &rollback_request)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_rollback_dir, rollback_authority, rollback_grant) = final_use_authority_and_grant(
        rollback_binding,
        "grant:runtime-canary:rollback",
        [0x32; 32],
    );
    let rollback_receipt = organs
        .recover_governed_topology(&rollback_authority, &rollback_grant, rollback_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(rollback_receipt.predecessor_generation, Generation::new(2)?);
    assert_eq!(rollback_receipt.successor_generation, Generation::new(3)?);

    let recovered_status = organs.status_json()?;
    let recovered = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(recovered.generation(), Generation::new(3)?);
    assert_eq!(recovered.route.source.system, baseline.route.source.system);
    assert_eq!(recovered.route.source.organ, baseline.route.source.organ);
    assert_eq!(recovered.route.source.driver, baseline.route.source.driver);
    assert_eq!(recovered.route.output_port, baseline.route.output_port);
    assert_eq!(recovered.route.targets, baseline.route.targets);

    // The independent Observer signs telemetry only after actual rollback succeeded.
    let mut evidence = Vec::new();
    evidence.extend_from_slice(apply_receipt.final_use_request_digest.as_array());
    evidence.extend_from_slice(rollback_receipt.final_use_request_digest.as_array());
    evidence.extend_from_slice(&recovered_status);
    let observation = StructuralCanaryObservationV1 {
        sequence: 1,
        health_digest: Digest32::of_bytes(&recovered_status),
        evidence_digest: Digest32::of_bytes(&evidence),
        regression_count: 0,
        safety_violation: true,
        lineage_mismatch: false,
        rollback_verified: true,
    };
    let (verifier, key, observer) = runtime_canary_observer();
    let attestation = sign_runtime_canary_observation(
        &verifier,
        &key,
        &observer,
        controller.plan_digest(),
        &observation,
    );
    let authenticated = observe_authenticated_structural_canary_v1(
        &mut controller,
        observation,
        &attestation,
        &verifier,
        50,
    )?;
    assert_eq!(authenticated.canary.state, StructuralCanaryStateV1::Aborted);
    assert_eq!(authenticated.observer_id, observer.principal_id);
    assert!(!authenticated.observer_authentication_digest.is_zero());
    assert_eq!(
        controller.finish()?.state,
        StructuralCanaryStateV1::Aborted
    );

    Ok(())
}
