use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::RuntimeStateStatus;
#[cfg(unix)]
use crate::RuntimeTopologyApplyRequestV1;
#[cfg(unix)]
use crate::RuntimeTopologyMigrationOwnerV1;
#[cfg(unix)]
use crate::RuntimeTopologySuccessorV1;
#[cfg(unix)]
use crate::runtime_topology_final_use_binding_v1;
#[cfg(unix)]
use crate::runtime_topology_recovery_final_use_binding_v1;
#[cfg(unix)]
use codex_hepta_control_plane::OrganMigrationError;
#[cfg(unix)]
use codex_hepta_control_plane::OrganStateMigrationV1;

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
    use codex_hepta_plasticity::ProposalWindowV2;
    use codex_hepta_plasticity::TopologyCandidateKindV2;
    use codex_hepta_plasticity::TopologyChangeV2;
    use codex_hepta_plasticity::TopologyOperationV2;
    use codex_hepta_plasticity::TopologyProposalRequestV2;
    use codex_hepta_plasticity::admit_governed_topology_v1;
    use codex_hepta_plasticity::build_writer_handoff_plan_v1;
    use codex_hepta_plasticity::propose_topology_v2;

    let migration = Digest32::of_bytes(b"runtime-topology-migration");
    let rollback = Digest32::of_bytes(b"runtime-topology-rollback");
    let handoff = build_writer_handoff_plan_v1(
        StableId::new("runtime.status.adapter").expect("module id"),
        StableId::new(format!(
            "runtime.owner.generation-{}",
            current.generation().get()
        ))
        .expect("from owner"),
        StableId::new(format!(
            "runtime.owner.generation-{}",
            successor.generation().get()
        ))
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
#[derive(Debug)]
struct RuntimeTopologyMigrationFixture {
    handoff_plan_digest: Digest32,
    migrations: Arc<AtomicUsize>,
    rollbacks: Arc<AtomicUsize>,
}

#[cfg(unix)]
impl OrganStateMigrationV1 for RuntimeTopologyMigrationFixture {
    fn snapshot(&mut self, _predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        Ok(b"runtime-topology-owned-state".to_vec())
    }

    fn migrate(
        &mut self,
        _snapshot: &[u8],
        _predecessor: Generation,
        _candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        self.migrations.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    fn rollback(
        &mut self,
        _snapshot: &[u8],
        _predecessor: Generation,
        _candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        self.rollbacks.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

#[cfg(unix)]
impl RuntimeTopologyMigrationOwnerV1 for RuntimeTopologyMigrationFixture {
    fn handoff_plan_digest(&self) -> Digest32 {
        self.handoff_plan_digest
    }
}

#[cfg(unix)]
fn runtime_topology_migration_for(
    governed: &codex_hepta_plasticity::GovernedTopologyProposalV1,
    candidate_id: &StableId,
) -> (
    Box<dyn RuntimeTopologyMigrationOwnerV1>,
    Arc<AtomicUsize>,
    Arc<AtomicUsize>,
) {
    let candidate = governed
        .proposal
        .candidates
        .iter()
        .find(|candidate| &candidate.candidate_id == candidate_id)
        .expect("topology candidate");
    let change = candidate.changes.first().expect("topology change");
    let handoff = governed
        .handoffs
        .iter()
        .find(|handoff| handoff.module_id == change.module_id)
        .expect("writer handoff");
    let migrations = Arc::new(AtomicUsize::new(0));
    let rollbacks = Arc::new(AtomicUsize::new(0));
    (
        Box::new(RuntimeTopologyMigrationFixture {
            handoff_plan_digest: handoff.plan_digest,
            migrations: Arc::clone(&migrations),
            rollbacks: Arc::clone(&rollbacks),
        }),
        migrations,
        rollbacks,
    )
}

#[cfg(unix)]
fn deterministic_test_nonce(label: &[u8]) -> [u8; 32] {
    *Digest32::of_bytes(label).as_array()
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
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

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
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;

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
            controller_id: StableId::new("controller:runtime-topology-canary").expect("controller"),
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
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
    use ed25519_dalek::Signer;

    let payload = structural_canary_observation_signing_payload_v1(plan_digest, observation)
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
    let (migration, migration_calls, rollback_calls) =
        runtime_topology_migration_for(&governed, &candidate_id);
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:accepted-topology")?,
        migration,
        successor,
    };
    let binding = runtime_topology_final_use_binding_v1(&current, &request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_authority_directory, authority, signed) = final_use_authority_and_grant(
        binding,
        "grant:runtime-topology:1",
        deterministic_test_nonce(b"runtime-topology-apply-nonce"),
    );

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
    assert_eq!(migration_calls.load(Ordering::SeqCst), 1);
    assert_eq!(rollback_calls.load(Ordering::SeqCst), 0);

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
fn topology_migration_owner_must_bind_exact_handoff_plan() -> Result<()> {
    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(std::env::temp_dir().join(format!(
        "hepta-topology-migration-binding-{}",
        std::process::id()
    )))?;
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
        governed_topology_for_runtime("migration-binding", &current, &successor_snapshot);
    let migrations = Arc::new(AtomicUsize::new(0));
    let rollbacks = Arc::new(AtomicUsize::new(0));
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:migration-binding")?,
        migration: Box::new(RuntimeTopologyMigrationFixture {
            handoff_plan_digest: Digest32::of_bytes(b"wrong-handoff-plan"),
            migrations: Arc::clone(&migrations),
            rollbacks: Arc::clone(&rollbacks),
        }),
        successor,
    };

    assert!(matches!(
        runtime_topology_final_use_binding_v1(&current, &request),
        Err(crate::RuntimeTopologyExecutionError::Binding)
    ));
    assert_eq!(migrations.load(Ordering::SeqCst), 0);
    assert_eq!(rollbacks.load(Ordering::SeqCst), 0);
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
    let (migration, migration_calls, rollback_calls) =
        runtime_topology_migration_for(&governed, &candidate_id);
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:revoked-topology")?,
        migration,
        successor,
    };
    let binding = runtime_topology_final_use_binding_v1(&current, &request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_authority_directory, authority, signed) = final_use_authority_and_grant(
        binding,
        "grant:runtime-topology:revoked",
        deterministic_test_nonce(b"runtime-topology-revoked-nonce"),
    );
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
    assert_eq!(migration_calls.load(Ordering::SeqCst), 0);
    assert_eq!(rollback_calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[cfg(unix)]
#[test]
fn authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics()
-> Result<()> {
    use codex_hepta_intelligence::observe_authenticated_structural_canary_v1;
    use codex_hepta_plasticity::DurableTopologyProposalRegistryV1;
    use codex_hepta_plasticity::StructuralCanaryControllerV1;
    use codex_hepta_plasticity::StructuralCanaryObservationV1;
    use codex_hepta_plasticity::StructuralCanaryStateV1;
    use codex_hepta_plasticity::build_structural_canary_plan_v1;

    let calls = Arc::new(AtomicUsize::new(0));
    let root = HeptaStateRoot::parse(
        std::env::temp_dir().join(format!("hepta-topology-real-canary-{}", std::process::id())),
    )?;
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

    let (apply_migration, apply_migration_calls, apply_rollback_calls) =
        runtime_topology_migration_for(&governed, &candidate_id);
    let apply_request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:runtime-canary-apply")?,
        migration: apply_migration,
        successor,
    };
    let apply_binding = runtime_topology_final_use_binding_v1(&baseline, &apply_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_apply_dir, apply_authority, apply_grant) = final_use_authority_and_grant(
        apply_binding,
        "grant:runtime-canary:apply",
        deterministic_test_nonce(b"runtime-canary-apply-nonce"),
    );
    let apply_receipt = organs
        .apply_governed_topology(&apply_authority, &apply_grant, apply_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(apply_receipt.predecessor_generation, Generation::new(1)?);
    assert_eq!(apply_receipt.successor_generation, Generation::new(2)?);
    assert_eq!(apply_migration_calls.load(Ordering::SeqCst), 1);
    assert_eq!(apply_rollback_calls.load(Ordering::SeqCst), 0);

    // Force a real live-host failure after cutover, rather than synthesizing a boolean-only fault.
    {
        let mut guard = organs
            .host
            .lock()
            .map_err(|_| anyhow::anyhow!("test host poisoned"))?;
        let live = guard.as_mut().map_err(|error| anyhow::anyhow!("{error}"))?;
        live.host.stop_all()?;
    }
    assert!(organs.status_json().is_err());

    // Rollback is an authorized new transition (generation 2 -> 3), not time travel.
    let failed = organs
        .topology_snapshot()
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let rollback_host = build_host_generation(root, Arc::clone(&state), Generation::new(3)?)?;
    let rollback_successor =
        RuntimeTopologySuccessorV1::new(rollback_host.host, rollback_host.route)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
    let rollback_snapshot = rollback_successor.snapshot();
    let (rollback_governed, rollback_candidate_id) =
        governed_topology_for_runtime("canary-rollback", &failed, &rollback_snapshot);
    let (rollback_migration, rollback_migration_calls, rollback_owner_rollbacks) =
        runtime_topology_migration_for(&rollback_governed, &rollback_candidate_id);
    let rollback_request = RuntimeTopologyApplyRequestV1 {
        governed: rollback_governed,
        candidate_id: rollback_candidate_id,
        accepted_subject_id: StableId::new("operator:runtime-canary-rollback")?,
        migration: rollback_migration,
        successor: rollback_successor,
    };
    let rollback_binding =
        runtime_topology_recovery_final_use_binding_v1(&failed, &rollback_request)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
    let (_rollback_dir, rollback_authority, rollback_grant) = final_use_authority_and_grant(
        rollback_binding,
        "grant:runtime-canary:rollback",
        deterministic_test_nonce(b"runtime-canary-rollback-nonce"),
    );
    let rollback_receipt = organs
        .recover_governed_topology(&rollback_authority, &rollback_grant, rollback_request)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    assert_eq!(rollback_receipt.predecessor_generation, Generation::new(2)?);
    assert_eq!(rollback_receipt.successor_generation, Generation::new(3)?);
    assert_eq!(rollback_migration_calls.load(Ordering::SeqCst), 1);
    assert_eq!(rollback_owner_rollbacks.load(Ordering::SeqCst), 0);

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
    assert_eq!(controller.finish()?.state, StructuralCanaryStateV1::Aborted);

    Ok(())
}

/// Even a valid first-party governed successor, signed route and Final-use
/// fixture MUST NOT mutate the real runtime without an original shared
/// Control/Neuron durable Begin/Commit owner. No imitation route is used.
#[cfg(all(unix, feature = "cell-split-cns-port"))]
#[test]
fn cell_split_cns_runtime_port_denies_real_governed_runtime_without_control() -> Result<()> {
    use std::fs;
    use std::io::Write as _;
    use std::os::unix::fs::OpenOptionsExt as _;
    use std::os::unix::fs::PermissionsExt as _;
    use std::path::PathBuf;

    use codex_hepta_contracts::SignedFinalUseGrant;
    use codex_hepta_operator_acceptance::CellSplitCnsLiveRouteV1;
    use codex_hepta_operator_acceptance::CellSplitCnsRouteBindingV1;
    use codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1;
    use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
    use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;
    use sha2::Digest as _;
    use sha2::Sha256;

    use crate::CellSplitCnsKernelRuntimePortV1;
    use crate::CellSplitCnsKernelWitnessV1;
    use crate::cell_split_cns_live_route_signing_bytes_v1;

    struct DurableTestCnsWitness {
        signer: SigningKey,
        original_path: PathBuf,
        _authority_dir: tempfile::TempDir,
        successor: Option<(SignedFinalUseGrant, RuntimeTopologyApplyRequestV1)>,
    }

    impl CellSplitCnsKernelWitnessV1 for DurableTestCnsWitness {
        type Error = String;

        fn verify_preconditions(
            &mut self,
            plan: &CellSplitExecutionPlanV1,
            intent: &CellSplitExecutionIntentV1,
        ) -> std::result::Result<(), String> {
            if plan.scope_digest != "11".repeat(32)
                || intent.previous_receipt_digest != "77".repeat(32)
            {
                return Err("missing signed migration predecessor".into());
            }
            Ok(())
        }

        fn signed_current_route(
            &mut self,
            runtime: &RuntimeTopologySnapshotV1,
            nonce: &str,
        ) -> std::result::Result<CellSplitCnsLiveRouteV1, String> {
            let artifact = if runtime.generation().get() == 2 {
                "33".repeat(32)
            } else {
                "22".repeat(32)
            };
            let mut observed = CellSplitCnsLiveRouteV1 {
                cns_id: runtime.cns_id().to_string(),
                scope_digest: "11".repeat(32),
                generation: runtime.generation().get(),
                artifact_digest: artifact,
                route_digest: runtime.hierarchy_digest().to_string(),
                route_fence_digest: "55".repeat(32),
                authority_epoch: 7,
                old_writer_fenced: true,
                unknown_effect_count: 0,
                challenge_nonce: nonce.to_owned(),
                live_runtime_proof_bytes: Vec::new(),
            };
            observed.live_runtime_proof_bytes = self
                .signer
                .sign(&cell_split_cns_live_route_signing_bytes_v1(&observed)?)
                .to_bytes()
                .to_vec();
            Ok(observed)
        }

        fn take_admitted_successor(
            &mut self,
            _plan: &CellSplitExecutionPlanV1,
            _binding: &CellSplitCnsRouteBindingV1,
            _intent: &CellSplitExecutionIntentV1,
        ) -> std::result::Result<(SignedFinalUseGrant, RuntimeTopologyApplyRequestV1), String>
        {
            self.successor
                .take()
                .ok_or_else(|| "signed successor consumed".into())
        }

        fn persist_actual_runtime_receipt(
            &mut self,
            plan: &CellSplitExecutionPlanV1,
            binding: &CellSplitCnsRouteBindingV1,
            intent: &CellSplitExecutionIntentV1,
            actual: &RuntimeTopologyApplyReceiptV1,
        ) -> std::result::Result<(), String> {
            if actual.predecessor_generation.get() != plan.parent_generation
                || actual.successor_generation.get() != plan.child_generation
                || actual.predecessor_hierarchy_digest.to_string()
                    != binding.predecessor_route_digest
                || actual.successor_hierarchy_digest.to_string() != binding.successor_route_digest
            {
                return Err("runtime receipt drift".into());
            }
            let mut record = CellSplitCnsRuntimeCommitV1 {
                idempotency_key: intent.idempotency_key.clone(),
                cns_id: binding.cns_id.clone(),
                predecessor_route_digest: binding.predecessor_route_digest.clone(),
                successor_route_digest: binding.successor_route_digest.clone(),
                predecessor_generation: plan.parent_generation,
                successor_generation: plan.child_generation,
                authority_epoch: binding.authority_epoch,
                committed_sequence: 9,
                original_runtime_receipt_bytes: Vec::new(),
                original_runtime_signature_bytes: Vec::new(),
            };
            record.original_runtime_receipt_bytes =
                CellSplitCnsRuntimeAttestationV1::for_commit(plan, &record)
                    .canonical_bytes()
                    .map_err(str::to_string)?;
            record.original_runtime_signature_bytes = self
                .signer
                .sign(&record.original_runtime_receipt_bytes)
                .to_bytes()
                .to_vec();
            let bytes = serde_json::to_vec(&record).map_err(|e| e.to_string())?;
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&self.original_path)
                .map_err(|e| e.to_string())?;
            file.write_all(&bytes)
                .and_then(|_| file.sync_all())
                .map_err(|e| e.to_string())?;
            fs::File::open(self.original_path.parent().ok_or("parent missing")?)
                .and_then(|dir| dir.sync_all())
                .map_err(|e| e.to_string())
        }

        fn read_original_commit(
            &mut self,
            _key: &str,
        ) -> std::result::Result<Option<CellSplitCnsRuntimeCommitV1>, String> {
            match fs::read(&self.original_path) {
                Ok(bytes) => serde_json::from_slice(&bytes)
                    .map(Some)
                    .map_err(|e| e.to_string()),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
                Err(e) => Err(e.to_string()),
            }
        }

        fn current_durable_sequence(&mut self, _cns_id: &str) -> std::result::Result<u64, String> {
            Ok(if self.original_path.exists() { 9 } else { 1 })
        }
    }

    let calls = Arc::new(AtomicUsize::new(0));
    let root =
        HeptaStateRoot::parse(std::env::temp_dir().join("hepta-cell-split-real-kernel-e2e"))?;
    let state: Arc<dyn RuntimeStateAdapter> = Arc::new(ObservedAdapter(Arc::clone(&calls)));
    let runtime = crate::HeptaRuntime::from_adapter(root.clone(), Arc::clone(&state));
    let before = runtime.topology_snapshot()?;
    let successor_host = build_host_generation(
        root.clone(),
        Arc::clone(&state),
        before.generation().next()?,
    )?;
    let successor = RuntimeTopologySuccessorV1::new(successor_host.host, successor_host.route)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let expected = successor.snapshot();
    let (governed, candidate_id) =
        governed_topology_for_runtime("cell-split-port", &before, &expected);
    let (migration, migration_calls, rollback_calls) =
        runtime_topology_migration_for(&governed, &candidate_id);
    let request = RuntimeTopologyApplyRequestV1 {
        governed,
        candidate_id,
        accepted_subject_id: StableId::new("operator:split-cns-port")?,
        migration,
        successor,
    };
    let runtime_final_use = runtime_topology_final_use_binding_v1(&before, &request)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let (authority_dir, authority, signed_grant) = final_use_authority_and_grant(
        runtime_final_use,
        "grant:runtime-cell-split-port",
        deterministic_test_nonce(b"cell-split-cns-port-final-use"),
    );
    let plan = CellSplitExecutionPlanV1 {
        split_id: "split.cns.real-runtime".into(),
        scope_digest: "11".repeat(32),
        parent_generation: before.generation().get(),
        child_generation: expected.generation().get(),
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "cas-owner".into(),
            "migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    };
    let binding = CellSplitCnsRouteBindingV1 {
        cns_id: before.cns_id().to_string(),
        predecessor_route_digest: before.hierarchy_digest().to_string(),
        successor_route_digest: expected.hierarchy_digest().to_string(),
        authority_epoch: 7,
    };
    let previous_receipt_digest = "77".repeat(32);
    let plan_digest = plan.digest().map_err(|e| anyhow::anyhow!("{e}"))?;
    let idempotency_key = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                plan_digest,
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                previous_receipt_digest,
            )
            .as_bytes()
        ),
    );
    let intent = CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: "cns-owner".into(),
        idempotency_key,
        previous_receipt_digest,
    };
    let witness_directory = tempfile::tempdir()?;
    let runtime_signer = SigningKey::from_bytes(&[0x6b; 32]);
    let original_path = witness_directory.path().join("original-cns-runtime.json");
    let pinned_authority = Arc::new(authority);
    let witness = DurableTestCnsWitness {
        signer: runtime_signer.clone(),
        original_path: original_path.clone(),
        _authority_dir: authority_dir,
        successor: Some((signed_grant, request)),
    };
    let mut port = CellSplitCnsKernelRuntimePortV1::new(
        runtime.clone(),
        Arc::clone(&pinned_authority),
        plan.clone(),
        binding.clone(),
        intent.clone(),
        runtime_signer.verifying_key(),
        witness,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    // This is a REAL serving Runtime host and a valid signed predecessor,
    // signed one-use grant, and admitted successor candidate, but NONE is a
    // substitute for original Control's durable same-owner B/C transaction.
    port.verify_preconditions(&plan, &intent)
        .map_err(anyhow::Error::msg)?;
    let live = port
        .inspect_live(&binding.cns_id, &plan.scope_digest, &"aa".repeat(32))
        .map_err(anyhow::Error::msg)?;
    port.verify_live(&live).map_err(anyhow::Error::msg)?;
    assert_eq!(live.generation, plan.parent_generation);
    let denied = port
        .publish_once(&plan, &binding, &intent)
        .expect_err("missing durable Control Begin/Commit must deny real CNS mutation");
    assert!(
        denied.contains("no shared durable Control/Neuron cutover transaction"),
        "denial must be the first original Control safety fence"
    );
    assert_eq!(runtime.topology_snapshot()?, before);
    assert_eq!(migration_calls.load(Ordering::SeqCst), 0);
    assert_eq!(rollback_calls.load(Ordering::SeqCst), 0);
    assert!(
        port.read_original_commit(&intent.idempotency_key)
            .map_err(anyhow::Error::msg)?
            .is_none(),
        "denied cutover cannot mint an original signed runtime receipt"
    );
    assert_eq!(
        port.committed_sequence(&binding.cns_id)
            .map_err(anyhow::Error::msg)?,
        1,
        "no durable successor sequence is permitted"
    );
    assert!(!original_path.exists(), "denied cutover has no durable effect");
    assert!(port.publish_once(&plan, &binding, &intent).is_err());
    assert_eq!(migration_calls.load(Ordering::SeqCst), 0);

    // Restart must not manufacture a successor or a positive commit from a
    // signed candidate which never crossed the durable Control transaction.
    drop(port);
    let after_restart = crate::HeptaRuntime::from_adapter(root, state);
    assert_eq!(after_restart.topology_snapshot()?, before);
    let restarted_witness = DurableTestCnsWitness {
        signer: runtime_signer.clone(),
        original_path: original_path.clone(),
        _authority_dir: tempfile::tempdir()?,
        successor: None,
    };
    let restarted_port = CellSplitCnsKernelRuntimePortV1::new(
        after_restart,
        pinned_authority,
        plan.clone(),
        binding.clone(),
        intent.clone(),
        runtime_signer.verifying_key(),
        restarted_witness,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    let owner_root = tempfile::tempdir()?;
    fs::set_permissions(owner_root.path(), fs::Permissions::from_mode(0o700))?;
    let mut owner = codex_hepta_operator_acceptance::CellSplitCnsCutoverOwnerV1::open(
        owner_root.path(),
        plan,
        binding,
        restarted_port,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    use codex_hepta_operator_acceptance::CellSplitDurableEffectBackendV1 as _;
    assert!(
        owner
            .read_committed(&intent)
            .map_err(|error| anyhow::anyhow!("{error}"))?
            .is_none(),
        "missing original Control/CNS handoff must return no committed effect",
    );
    assert!(!original_path.exists(), "restart may not manufacture a CNS commit");
    Ok(())
}
