use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::CellParameterBundleManifestV1;
use crate::TypedRoleArtifactEvidenceV1;
use crate::TypedRoleArtifactOwnerV1;
use codex_hepta_types::CellCapabilityProfileV1;
use codex_hepta_types::CellPersistenceClassV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::CellUpdateModeV1;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
}

fn definition() -> CellDefinitionV2 {
    let role = CellRoleV1::Representation;
    let owner = id("hepta.rep.owner");
    let profile = CellCapabilityProfileV1 {
        role,
        observation_schema_digest: digest(1),
        output_schema_digest: digest(2),
        state_schema_digest: digest(3),
        input_port_digest: digest(4),
        output_port_digest: digest(5),
        termination_port_digest: digest(6),
        owner_module: owner.clone(),
        persistence_class: CellPersistenceClassV1::Checkpointed,
        update_mode: CellUpdateModeV1::OutcomeProposal,
        fallback_role: Some(CellRoleV1::MemoryRead),
        objective_digest: digest(7),
        resource_budget_digest: digest(8),
        evaluation_profile_digest: digest(9),
        authority: AuthorityPosture::DENY_ALL,
    };
    CellDefinitionV2 {
        cell_id: id("cell.qualification.rep"),
        generation: Generation::new(2).expect("generation"),
        scope_digest: digest(10),
        lineage_digest: digest(11),
        role,
        capability_profile: profile.clone(),
        parameter_bundle_digest: digest(12),
        state_schema_digest: profile.state_schema_digest,
        port_abi_digest: digest(13),
        owner_module: owner,
        objective_digest: profile.objective_digest,
        fallback_role: profile.fallback_role,
        evidence_owner: id("observer.rep"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn parameter_manifest(
    definition: &CellDefinitionV2,
    bytes: &[u8],
) -> CellParameterBundleManifestV1 {
    let mut manifest = CellParameterBundleManifestV1 {
        artifact_id: definition.cell_id.clone(),
        cell_id: definition.cell_id.clone(),
        parent_artifact_id: id("parent.rep.parameters"),
        generation: definition.generation,
        parent_bundle_digest: digest(20),
        child_bundle_digest: Digest32::of_bytes(bytes),
        scope_digest: definition.scope_digest,
        definition_digest: definition.content_digest().expect("definition digest"),
        lineage_digest: definition.lineage_digest,
        objective_digest: definition.objective_digest,
        compatibility_digest: digest(21),
        inheritance_digest: digest(22),
        split_digest: digest(23),
        producer_id: id("producer.rep"),
        encoded_size_bytes: bytes.len() as u64,
        manifest_digest: Digest32::ZERO,
    };
    manifest.manifest_digest = manifest.content_digest();
    manifest
}

#[derive(Clone, Debug)]
struct FixtureExecutor;

impl RoleQualificationStepExecutorV1 for FixtureExecutor {
    fn execute_step(
        &mut self,
        definition: &CellDefinitionV2,
        input_frontier_digest: Digest32,
        predecessor_state_digest: Digest32,
    ) -> Result<RoleQualificationExecutionV1, RoleQualificationExecutorErrorV1> {
        let mut state_bytes = b"representation-successor-v1".to_vec();
        state_bytes.extend_from_slice(input_frontier_digest.as_array());
        state_bytes.extend_from_slice(predecessor_state_digest.as_array());
        let step = CellStepReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: definition.role,
            capability_digest: definition
                .capability_digest()
                .map_err(|_| RoleQualificationExecutorErrorV1::Binding("capability"))?,
            input_frontier_digest,
            state_predecessor_digest: predecessor_state_digest,
            state_successor_digest: Digest32::of_bytes(&state_bytes),
            output_digest: digest(30),
            uncertainty_ppm: 1,
            ood_ppm: 2,
            resource_receipt_digest: digest(31),
            evidence_digest: digest(32),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(RoleQualificationExecutionV1 { step, state_bytes })
    }
}

fn setup() -> (
    ProductionRoleQualificationOwnerV1<FixtureExecutor>,
    std::path::PathBuf,
) {
    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);
    let root = std::env::temp_dir().join(format!(
        "hepta-production-role-qualification-{}",
        NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).expect("artifact root");
    let artifact_relative = std::path::PathBuf::from("representation.bundle");
    let bytes = b"representation-parameter-bundle-v1";
    let mut definition = definition();
    definition.parameter_bundle_digest = Digest32::of_bytes(bytes);
    let manifest = parameter_manifest(&definition, bytes);

    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register.parent.rep"),
            manifest: ArtifactManifest {
                artifact_id: manifest.parent_artifact_id.clone(),
                kind: ArtifactKind::Parameters,
                generation: Generation::new(1).expect("generation"),
                predecessor_id: None,
                content_digest: manifest.parent_bundle_digest,
                objective_digest: manifest.objective_digest,
                support_digest: manifest.lineage_digest,
                producer_id: id("producer.parent.rep"),
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: 1,
            },
        })
        .expect("parent registry");
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register.child.rep"),
            manifest: manifest.as_registry_manifest(),
        })
        .expect("child registry");

    let key = SigningKey::from_bytes(&[41; 32]);
    let artifact_owner = ArtifactCasOwnerV1::new(id("cas.owner.rep"), key.clone()).expect("CAS");
    let artifact_write = artifact_owner
        .write_candidate(
            id("write.rep"),
            &root,
            &artifact_relative,
            &registry,
            &manifest.artifact_id,
            bytes,
            None,
            None,
        )
        .expect("write artifact");
    let artifact_file = std::fs::File::open(root.join(&artifact_relative)).expect("artifact file");
    let (loaded_bytes, artifact_load) = artifact_owner
        .load_candidate(
            id("load.rep"),
            artifact_file,
            &registry,
            &manifest.artifact_id,
            &artifact_write,
            &artifact_relative,
            None,
            None,
        )
        .expect("load artifact");
    assert_eq!(loaded_bytes, bytes);

    let mut state_owner =
        DurableLearnedRoleOwnerV1::new(definition.clone(), id("state.owner.rep"), key)
            .expect("state owner");
    let initial_state = state_owner
        .seed_initial_state(
            id("state.genesis.rep"),
            b"representation-genesis".to_vec(),
            None,
            None,
        )
        .expect("genesis");
    let state_path = root.join("state.snapshot");
    state_owner.persist(&state_path).expect("state snapshot");

    let typed_owner = TypedRoleArtifactOwnerV1::new(id("typed.owner.rep")).expect("typed owner");
    let evidence = TypedRoleArtifactEvidenceV1 {
        provenance_digest: digest(40),
        cas_receipt_digest: artifact_write.content_digest(),
        registry_receipt_digest: artifact_load.registry_head_digest,
        state_checkpoint_digest: initial_state.content_digest(),
        reload_receipt_digest: artifact_load.content_digest(),
    };
    let (artifact, artifact_receipt) = typed_owner
        .bind(definition.clone(), manifest, evidence)
        .expect("typed artifact");
    let owner = ProductionRoleQualificationOwnerV1::new(
        definition,
        artifact,
        artifact_receipt,
        artifact_owner,
        artifact_write,
        registry,
        &root,
        artifact_relative,
        state_owner,
        state_path,
        initial_state,
        FixtureExecutor,
        None,
        None,
    )
    .expect("qualification owner");
    (owner, root)
}

#[test]
fn qualification_owner_reloads_cas_commits_runtime_state_and_restarts() {
    let (mut owner, root) = setup();
    let artifact = owner.reload_artifact().expect("reload");
    assert_eq!(
        artifact.origin,
        RoleQualificationEvidenceOriginV1::RepositoryQualification
    );
    let input = digest(50);
    let step = owner.step(input).expect("step");
    assert_eq!(step.input_frontier_digest, input);
    assert_eq!(
        owner.current_state().state_digest,
        step.state_successor_digest
    );
    let restart = owner
        .exercise_fault(RoleQualificationFaultKindV1::CheckpointRestart)
        .expect("restart");
    assert!(restart.recovered);
    assert!(!restart.no_resurrection_verified);
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn qualification_owner_rollback_uses_checkpoint_owner_and_rejects_unsupported_faults() {
    let (mut owner, root) = setup();
    owner.reload_artifact().expect("reload");
    owner.step(digest(51)).expect("step");
    let rollback = owner
        .exercise_fault(RoleQualificationFaultKindV1::Rollback)
        .expect("rollback");
    assert!(rollback.recovered);
    assert!(rollback.rollback_verified);
    assert_eq!(
        owner.current_state().state_digest,
        owner.initial_state.state_digest
    );
    assert_eq!(
        owner.exercise_fault(RoleQualificationFaultKindV1::PowerLossRecovery),
        Err(RoleQualificationOwnerErrorV1::FaultUnavailable)
    );
    std::fs::remove_dir_all(root).expect("cleanup");
}
