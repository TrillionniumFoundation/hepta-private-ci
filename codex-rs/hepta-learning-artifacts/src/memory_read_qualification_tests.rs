use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::CellParameterBundleManifestV1;
use crate::MemoryReadStepReceiptV1;
use crate::StateCommitReceiptV1;
use codex_hepta_cell_roles::CellRoleStepV1;
use codex_hepta_cell_roles::MemoryReadResultV1;
use codex_hepta_cell_roles::RoleQualificationFaultKindV1;
use codex_hepta_cell_roles::RoleQualificationOwnerErrorV1;
use codex_hepta_memory_retrieval::RetrievalReceipt;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellCapabilityProfileV1;
use codex_hepta_types::CellPersistenceClassV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::CellUpdateModeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
}

fn definition() -> CellDefinitionV2 {
    let role = CellRoleV1::MemoryRead;
    let capability = CellCapabilityProfileV1 {
        role,
        observation_schema_digest: digest(1),
        output_schema_digest: digest(2),
        state_schema_digest: digest(3),
        input_port_digest: digest(4),
        output_port_digest: digest(5),
        termination_port_digest: digest(6),
        owner_module: id("hepta.memory-read.owner"),
        persistence_class: CellPersistenceClassV1::Checkpointed,
        update_mode: CellUpdateModeV1::InferenceOnly,
        fallback_role: None,
        objective_digest: digest(7),
        resource_budget_digest: digest(8),
        evaluation_profile_digest: digest(9),
        authority: AuthorityPosture::DENY_ALL,
    };
    CellDefinitionV2 {
        cell_id: id("cell.memory-read.qualification"),
        generation: Generation::new(2).expect("generation"),
        scope_digest: digest(10),
        lineage_digest: digest(11),
        role,
        capability_profile: capability,
        parameter_bundle_digest: digest(12),
        state_schema_digest: digest(3),
        port_abi_digest: digest(13),
        owner_module: id("hepta.memory-read.owner"),
        objective_digest: digest(7),
        fallback_role: None,
        evidence_owner: id("observer.memory-read"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn manifest(definition: &CellDefinitionV2, bytes: &[u8]) -> CellParameterBundleManifestV1 {
    let mut manifest = CellParameterBundleManifestV1 {
        artifact_id: definition.cell_id.clone(),
        cell_id: definition.cell_id.clone(),
        parent_artifact_id: id("parent.memory-read"),
        generation: definition.generation,
        parent_bundle_digest: digest(20),
        child_bundle_digest: Digest32::of_bytes(bytes),
        scope_digest: definition.scope_digest,
        definition_digest: definition.content_digest().expect("definition"),
        lineage_digest: definition.lineage_digest,
        objective_digest: definition.objective_digest,
        compatibility_digest: digest(21),
        inheritance_digest: digest(22),
        split_digest: digest(23),
        producer_id: id("producer.memory-read"),
        encoded_size_bytes: bytes.len() as u64,
        manifest_digest: Digest32::ZERO,
    };
    manifest.manifest_digest = manifest.content_digest();
    manifest
}

fn registry(manifest: &CellParameterBundleManifestV1) -> ArtifactRegistry {
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register.parent.memory-read"),
            manifest: ArtifactManifest {
                artifact_id: manifest.parent_artifact_id.clone(),
                kind: ArtifactKind::Parameters,
                generation: Generation::new(1).expect("generation"),
                predecessor_id: None,
                content_digest: manifest.parent_bundle_digest,
                objective_digest: manifest.objective_digest,
                support_digest: manifest.lineage_digest,
                producer_id: id("producer.parent.memory-read"),
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: 1,
            },
        })
        .expect("parent registry");
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register.child.memory-read"),
            manifest: manifest.as_registry_manifest(),
        })
        .expect("child registry");
    registry
}

#[derive(Clone, Debug)]
struct FixtureExecutor;

impl MemoryReadQualificationStepExecutorV1 for FixtureExecutor {
    fn execute_step(
        &mut self,
        definition: &CellDefinitionV2,
        input_frontier_digest: Digest32,
        predecessor_state_digest: Digest32,
    ) -> Result<MemoryReadQualificationExecutionV1, MemoryReadQualificationExecutorErrorV1> {
        let state_bytes = b"memory-read-successor-v2".to_vec();
        let capability_digest = definition
            .capability_digest()
            .map_err(|_| MemoryReadQualificationExecutorErrorV1::Binding("capability"))?;
        let step = codex_hepta_types::CellStepReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: CellRoleV1::MemoryRead,
            capability_digest,
            input_frontier_digest,
            state_predecessor_digest: predecessor_state_digest,
            state_successor_digest: Digest32::of_bytes(&state_bytes),
            output_digest: digest(30),
            uncertainty_ppm: 0,
            ood_ppm: 0,
            resource_receipt_digest: digest(31),
            evidence_digest: digest(32),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        let result = MemoryReadResultV1 {
            recall_receipt_digest: digest(33),
            snapshot_digest: digest(34),
            result_count: 1,
            omitted_count: 0,
            freshness_bound_digest: digest(35),
        };
        let role_step = CellRoleStepV1 {
            result: result.clone(),
            receipt: step,
        };
        let retrieval = RetrievalReceipt {
            query_id: id("query.memory-read"),
            snapshot_digest: digest(34),
            receipt_digest: digest(33),
            results: Vec::new(),
            omitted_count: 0,
            authority: AuthorityPosture::DENY_ALL,
        };
        let receipt = MemoryReadStepReceiptV1 {
            artifact_digest: digest(40),
            query_digest: input_frontier_digest,
            retrieval_receipt_digest: retrieval.receipt_digest,
            cell_step_receipt: role_step.receipt.clone(),
            replay_digest: digest(41),
        };
        Ok(MemoryReadQualificationExecutionV1 {
            execution: MemoryReadExecutionV1 {
                result,
                role_step,
                receipt,
            },
            state_bytes,
        })
    }
}

fn setup() -> (
    MemoryReadQualificationOwnerV1<FixtureExecutor>,
    std::path::PathBuf,
    StateCommitReceiptV1,
) {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let root = std::env::temp_dir().join(format!(
        "hepta-memory-read-qualification-{}",
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).expect("root");
    let relative = std::path::PathBuf::from("memory-read.bundle");
    let bytes = b"memory-read-opaque-bundle-v2";
    let mut definition = definition();
    definition.parameter_bundle_digest = Digest32::of_bytes(bytes);
    let manifest = manifest(&definition, bytes);
    let registry = registry(&manifest);
    let key = SigningKey::from_bytes(&[43; 32]);
    let cas_owner = ArtifactCasOwnerV1::new(id("cas.memory-read"), key.clone()).expect("cas");
    let artifact_owner =
        MemoryReadArtifactOwnerV1::new(id("artifact.memory-read")).expect("artifact owner");
    let materialized = artifact_owner
        .materialize_bundle(
            &cas_owner,
            id("write.memory-read"),
            &root,
            &relative,
            &registry,
            definition.clone(),
            manifest,
            bytes,
            None,
            None,
        )
        .expect("materialized");
    let mut state_owner =
        DurableMemoryReadStateOwnerV1::new(definition.clone(), id("state.memory-read"), key)
            .expect("state owner");
    let initial = state_owner
        .seed_initial_state(
            id("genesis.memory-read"),
            b"memory-read-genesis".to_vec(),
            None,
            None,
        )
        .expect("initial state");
    let state_path = root.join("state.snapshot");
    state_owner.persist(&state_path).expect("state snapshot");
    let owner = MemoryReadQualificationOwnerV1::new(
        definition,
        materialized.artifact,
        materialized.artifact_receipt,
        artifact_owner,
        cas_owner,
        materialized.write_receipt,
        registry,
        &root,
        relative,
        state_owner,
        state_path,
        initial.clone(),
        FixtureExecutor,
        None,
        None,
    )
    .expect("qualification owner");
    (owner, root, initial)
}

#[test]
fn memory_read_qualification_reloads_steps_restarts_and_rolls_back() {
    let (mut owner, root, initial) = setup();
    let artifact = owner.reload_artifact().expect("artifact reload");
    assert_eq!(artifact.role, CellRoleV1::MemoryRead);
    let step = owner.step(digest(50)).expect("step");
    assert_eq!(
        owner.current_state().state_digest,
        step.state_successor_digest
    );
    let restart = owner
        .exercise_fault(RoleQualificationFaultKindV1::CheckpointRestart)
        .expect("restart");
    assert!(restart.recovered);
    let rollback = owner
        .exercise_fault(RoleQualificationFaultKindV1::Rollback)
        .expect("rollback");
    assert!(rollback.rollback_verified);
    assert_eq!(owner.current_state(), &initial);
    std::fs::remove_dir_all(root).expect("cleanup");
}

#[test]
fn memory_read_qualification_refuses_external_faults() {
    let (mut owner, root, _) = setup();
    assert_eq!(
        owner.exercise_fault(RoleQualificationFaultKindV1::PowerLossRecovery),
        Err(RoleQualificationOwnerErrorV1::FaultUnavailable)
    );
    assert_eq!(
        owner.exercise_fault(RoleQualificationFaultKindV1::RouteFence),
        Err(RoleQualificationOwnerErrorV1::FaultUnavailable)
    );
    std::fs::remove_dir_all(root).expect("cleanup");
}
