//! Actual Agentd read/tick/SQLite/host-witness composition. This fixture's
//! verifier and registry are explicitly test-only, never production issuers.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramPopulationV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::MemoryCellCheckpointReadPinsV1;
use codex_hepta_memory::MemoryCellCheckpointReceiptV1;
use codex_hepta_memory::MemoryCellPersistencePlanV1;
use codex_hepta_memory::MemoryCellPersistencePositionV1;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::StableMemoryId;
use codex_hepta_memory::memory_cell_checkpoint_schema_digest_v1;
use codex_hepta_memory::memory_cell_owner_frontier_digests_v1;
use codex_hepta_memory_retrieval::decode_engram_checkpoint_v1;
use codex_hepta_memory_retrieval::decode_recall_checkpoint_v1;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::PreferenceState;
use codex_hepta_ndu::SubjectClass;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdMemoryCellPersistenceHostV1;
use crate::CurrentMemoryRetrievalContext;
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context::read_with_retrieval_context_and_learning;

#[derive(Deserialize, Serialize)]
struct Retained {
    manifest: MemoryCellManifestV1,
    sequence: u64,
    checkpoint: ContractDigestV1,
    cut: ContractDigestV1,
    anchor: CognitiveRecoveryAnchor,
}

struct TestRegistry {
    owner: AgentId,
    context: RetrievalExecutionContextV1,
    plan: Mutex<MemoryCellPersistencePlanV1>,
    witness: PathBuf,
    bootstrap_allowed: bool,
    fail_retention: AtomicBool,
    retention_gate: Mutex<Option<RetentionGate>>,
}

struct RetentionGate {
    entered: tokio::sync::oneshot::Sender<()>,
    release: std::sync::mpsc::Receiver<()>,
}

impl CurrentMemoryRetrievalContext for TestRegistry {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != 1 {
            return Err("test registry identity".into());
        }
        Ok(self.context.clone())
    }

    fn checkpoint_plan(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<MemoryCellPersistencePlanV1, String> {
        self.current(owner, body_generation)?;
        let mut plan = self.plan.lock().map_err(|error| error.to_string())?.clone();
        match std::fs::read(&self.witness) {
            Ok(bytes) => {
                let retained: Retained =
                    serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
                plan.position =
                    MemoryCellPersistencePositionV1::Resume(MemoryCellCheckpointReadPinsV1 {
                        manifest: retained.manifest,
                        checkpoint_digest: retained.checkpoint,
                        owner_cut_digest: retained.cut,
                    });
            }
            Err(error)
                if error.kind() == std::io::ErrorKind::NotFound && self.bootstrap_allowed => {}
            Err(error) => return Err(error.to_string()),
        }
        Ok(plan)
    }

    fn retain_checkpoint(
        &self,
        owner: &AgentId,
        generation: u64,
        expected: &MemoryCellPersistencePlanV1,
        receipt: &MemoryCellCheckpointReceiptV1,
        anchor: &CognitiveRecoveryAnchor,
    ) -> Result<(), String> {
        if self.fail_retention.load(Ordering::SeqCst) {
            return Err("injected independent witness failure".into());
        }
        if self.checkpoint_plan(owner, generation)? != *expected {
            return Err("test registry CAS".into());
        }
        if let Some(gate) = self.retention_gate.lock().unwrap().take() {
            gate.entered
                .send(())
                .map_err(|_| "retention gate dropped")?;
            gate.release
                .recv_timeout(std::time::Duration::from_secs(10))
                .map_err(|error| error.to_string())?;
        }
        let retained = Retained {
            manifest: expected.manifest.clone(),
            sequence: receipt.logical_sequence,
            checkpoint: receipt.checkpoint_digest,
            cut: receipt.owner_cut_digest,
            anchor: anchor.clone(),
        };
        let pending = self.witness.with_extension("pending");
        let bytes = serde_json::to_vec(&retained).map_err(|error| error.to_string())?;
        // Windows FlushFileBuffers requires a write-capable handle. Never
        // truncate an unrelated staged witness after a crash/retry.
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&pending)
        {
            Ok(mut staged) => {
                use std::io::Write;
                staged
                    .write_all(&bytes)
                    .map_err(|error| error.to_string())?;
                staged.sync_all().map_err(|error| error.to_string())?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let metadata =
                    std::fs::symlink_metadata(&pending).map_err(|error| error.to_string())?;
                if !metadata.file_type().is_file()
                    || std::fs::read(&pending).map_err(|error| error.to_string())? != bytes
                {
                    return Err("conflicting staged witness cannot be overwritten".into());
                }
                std::fs::OpenOptions::new()
                    .write(true)
                    .open(&pending)
                    .and_then(|file| file.sync_all())
                    .map_err(|error| error.to_string())?;
            }
            Err(error) => return Err(error.to_string()),
        }
        std::fs::rename(&pending, &self.witness).map_err(|error| error.to_string())?;
        #[cfg(unix)]
        std::fs::File::open(self.witness.parent().ok_or("witness parent")?)
            .and_then(|file| file.sync_all())
            .map_err(|error| error.to_string())?;
        Ok(())
    }
}

fn contract(digest: Digest32) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest).unwrap()
}
fn fixture_digest(label: &[u8]) -> ContractDigestV1 {
    contract(Digest32::of_bytes(label))
}

async fn plan(
    store: &CognitiveStore,
    owner: &AgentId,
    context: &RetrievalExecutionContextV1,
) -> MemoryCellPersistencePlanV1 {
    let cut = store
        .lane_c_snapshot(
            &CognitiveAccess::agent_private(owner.clone()),
            &CognitiveScope::AgentPrivate,
            crate::cognitive_context::now_seconds().unwrap(),
        )
        .await
        .unwrap();
    let (source, forget) = memory_cell_owner_frontier_digests_v1(&cut);
    let ndu = PreferenceState::genesis(
        StableId::new(owner.as_str()).unwrap(),
        SubjectClass::Agent,
        vec![AxisValue {
            axis: StableId::new("test-recall-quality").unwrap(),
            value: FixedQ32::ZERO,
        }],
    )
    .unwrap();
    MemoryCellPersistencePlanV1 {
        manifest: MemoryCellManifestV1 {
            schema_version: 1,
            cell_id: ContractIdV1::new("agentd-test-semantic-cell").unwrap(),
            role: MemoryCellRoleV1::Semantic,
            parent_cell_id: None,
            shared_base_digest: contract(context.generation_vector.model_digest),
            encoder_digest: contract(context.generation_vector.encoder_preprocessor_digest),
            adapter_artifact_digest: fixture_digest(b"test-only-no-adapter-execution"),
            head_artifact_digest: fixture_digest(b"test-only-no-head-execution"),
            state_schema_digest: contract(memory_cell_checkpoint_schema_digest_v1()),
            source_frontier_digest: contract(source),
            forget_frontier_digest: contract(forget),
            lineage_digest: fixture_digest(b"test-only-lineage"),
            modalities: [ModalityKindV1::Text].into_iter().collect(),
            populations: [EngramPopulationV1::SemanticConcept].into_iter().collect(),
            graph_generation: ContractGenerationV1::new(1).unwrap(),
            model_generation: ContractGenerationV1::new(1).unwrap(),
            max_active_cells: 1,
            max_state_bytes: 1_048_576,
        },
        retrieval_context_digest: context.binding_digest(),
        ndu_state_digest: contract(ndu.state_digest),
        resource_budget_units: 1000,
        position: MemoryCellPersistencePositionV1::Bootstrap,
    }
}

async fn writer(
    store: CognitiveStore,
    owner: &AgentId,
) -> (
    Arc<ProductionDurableWriter>,
    Arc<dyn ProductionAuthorityVerifier>,
) {
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"test-only-agentd-memory-cell-grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        crate::cognitive_context::now_seconds().unwrap() as u64 + 3600,
        ProductionAuthorityToken::from_verified_bytes(
            b"test-only-agentd-memory-cell-token".to_vec(),
        )
        .unwrap(),
    )
    .unwrap();
    let verifier: Arc<dyn ProductionAuthorityVerifier> =
        Arc::new(|grant: &ProductionAuthorityLease, expected: &AgentId| {
            if grant.agent_id != *expected
                || grant.grant_digest
                    != Sha256Digest::for_bytes(b"test-only-agentd-memory-cell-grant")
            {
                Err("test-only authority rejected".into())
            } else {
                Ok(())
            }
        });
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            Arc::clone(&verifier),
            "agentd-memory-cell-tests",
            /*generation*/ 1,
        )
        .await
        .unwrap(),
    );
    (writer, verifier)
}

async fn read(
    store: &CognitiveStore,
    registry: &Arc<TestRegistry>,
    host: &Arc<AgentdMemoryCellPersistenceHostV1>,
) -> Result<crate::CognitiveContextSnapshot, CognitiveContextError> {
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    read_with_retrieval_context_and_learning(
        store,
        &registry.owner,
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
        Some(&current),
        /*learning_sink*/ None,
        Some(host),
        Some(1),
    )
    .await
}

#[tokio::test]
async fn actual_agentd_tick_restores_graph_packet_and_advances_after_exact_restart() {
    let (temp, store, owner, context, excluded) = super::fixture(191).await;
    let initial = plan(&store, &owner, &context).await;
    let registry = Arc::new(TestRegistry {
        owner: owner.clone(),
        context: context.clone(),
        plan: Mutex::new(initial.clone()),
        witness: temp.path().join("independent-host-witness.json"),
        bootstrap_allowed: true,
        fail_retention: AtomicBool::new(false),
        retention_gate: Mutex::new(None),
    });
    let (writer, verifier) = writer(store.clone(), &owner).await;
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    let host =
        Arc::new(AgentdMemoryCellPersistenceHostV1::new(Arc::clone(&writer), current).unwrap());
    let first = read(&store, &registry, &host).await.unwrap();
    assert_eq!(first.items.len(), 1);
    assert_ne!(first.items[0].memory_id, excluded);
    let retained: Retained =
        serde_json::from_slice(&std::fs::read(&registry.witness).unwrap()).unwrap();
    let MemoryCellPersistencePositionV1::Resume(pins) =
        registry.checkpoint_plan(&owner, 1).unwrap().position
    else {
        panic!("retained checkpoint");
    };
    let loaded = writer
        .memory_cell_state_capability()
        .unwrap()
        .read_current(
            &CognitiveAccess::agent_private(owner.clone()),
            &CognitiveScope::AgentPrivate,
            &pins,
            crate::cognitive_context::now_seconds().unwrap(),
        )
        .await
        .unwrap();
    let graph = decode_engram_checkpoint_v1(
        loaded.state_bytes(),
        loaded.header().state_content_digest.digest(),
    )
    .unwrap();
    let recall = decode_recall_checkpoint_v1(
        loaded.recall_bytes(),
        loaded.header().recall_content_digest.digest(),
    )
    .unwrap();
    assert_eq!(graph, context.engram_snapshot);
    assert_eq!(
        recall.packet.packet_digest,
        loaded.header().recall_packet_digest.digest()
    );
    let authority = writer.authority().clone();
    drop(host);
    drop(writer);
    store.close().await;
    let layout = HeptaFleetRoot::parse(temp.path().join("fleet"))
        .unwrap()
        .layout()
        .agent(&owner);
    let reopened = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained.anchor),
        &authority,
        verifier.as_ref(),
    )
    .await
    .unwrap();
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            reopened.clone(),
            authority,
            verifier,
            "agentd-memory-cell-tests",
            /*generation*/ 1,
        )
        .await
        .unwrap(),
    );
    let registry = Arc::new(TestRegistry {
        owner: owner.clone(),
        context: context.clone(),
        plan: Mutex::new(initial),
        witness: registry.witness.clone(),
        bootstrap_allowed: false,
        fail_retention: AtomicBool::new(false),
        retention_gate: Mutex::new(None),
    });
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    let host = Arc::new(AgentdMemoryCellPersistenceHostV1::new(writer, current).unwrap());
    let cut = reopened
        .lane_c_snapshot(
            &CognitiveAccess::agent_private(owner.clone()),
            &CognitiveScope::AgentPrivate,
            crate::cognitive_context::now_seconds().unwrap(),
        )
        .await
        .unwrap();
    let session = host
        .prepare(
            &cut,
            &context,
            crate::cognitive_context::now_seconds().unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(session.prepared.restored_recall(), Some(&recall));
    drop(session);
    let second = read(&reopened, &registry, &host).await.unwrap();
    assert_eq!(second.items, first.items);
    let next: Retained =
        serde_json::from_slice(&std::fs::read(&registry.witness).unwrap()).unwrap();
    assert_eq!(next.sequence, 2);
    assert_ne!(next.checkpoint, retained.checkpoint);
}

#[tokio::test]
async fn failed_retention_preserves_actual_receipt_and_blocks_until_exact_acknowledgement() {
    let (temp, store, owner, context, _) = super::fixture(192).await;
    let registry = Arc::new(TestRegistry {
        owner: owner.clone(),
        plan: Mutex::new(plan(&store, &owner, &context).await),
        context,
        witness: temp.path().join("independent-host-witness.json"),
        bootstrap_allowed: true,
        fail_retention: AtomicBool::new(true),
        retention_gate: Mutex::new(None),
    });
    let (writer, _) = writer(store.clone(), &owner).await;
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    let host = Arc::new(AgentdMemoryCellPersistenceHostV1::new(writer, current).unwrap());
    assert!(matches!(
        read(&store, &registry, &host).await,
        Err(CognitiveContextError::MemoryCellPersistenceUnavailable)
    ));
    let pending = host.pending_checkpoint().await.unwrap();
    assert_eq!(pending.receipt.logical_sequence, 1);
    assert_ne!(
        Some(pending.receipt.checkpoint_digest.digest()),
        pending.shadow_candidate_digest
    );
    assert!(pending.shadow_candidate_digest.is_some());
    assert!(host.acknowledge_retained_checkpoint().await.is_err());
    assert!(matches!(
        read(&store, &registry, &host).await,
        Err(CognitiveContextError::MemoryCellPersistenceUnavailable)
    ));
    assert_eq!(
        host.pending_checkpoint().await.unwrap().receipt,
        pending.receipt
    );
    registry.fail_retention.store(false, Ordering::SeqCst);
    // Simulate a crash after staging but before rename. A conflicting
    // temporary witness must remain untouched; the identical staged
    // payload is replayable without a new or forged checkpoint.
    let staged_path = registry.witness.with_extension("pending");
    std::fs::write(&staged_path, b"foreign-staged-witness").unwrap();
    assert!(
        registry
            .retain_checkpoint(
                &owner,
                1,
                &pending.expected_plan,
                &pending.receipt,
                pending.recovery_anchor.as_ref().unwrap(),
            )
            .is_err()
    );
    assert_eq!(
        std::fs::read(&staged_path).unwrap(),
        b"foreign-staged-witness"
    );
    std::fs::remove_file(&staged_path).unwrap();
    let same = Retained {
        manifest: pending.expected_plan.manifest.clone(),
        sequence: pending.receipt.logical_sequence,
        checkpoint: pending.receipt.checkpoint_digest,
        cut: pending.receipt.owner_cut_digest,
        anchor: pending.recovery_anchor.clone().unwrap(),
    };
    std::fs::write(&staged_path, serde_json::to_vec(&same).unwrap()).unwrap();
    registry
        .retain_checkpoint(
            &owner,
            1,
            &pending.expected_plan,
            &pending.receipt,
            pending.recovery_anchor.as_ref().unwrap(),
        )
        .unwrap();
    // A host cannot acknowledge the same Resume pins while silently changing
    // the authenticated tick context. The durable receipt remains pending.
    let original = registry.plan.lock().unwrap().clone();
    for changed in [
        MemoryCellPersistencePlanV1 {
            resource_budget_units: original.resource_budget_units + 1,
            ..original.clone()
        },
        MemoryCellPersistencePlanV1 {
            ndu_state_digest: fixture_digest(b"different-host-ndu-state"),
            ..original.clone()
        },
    ] {
        *registry.plan.lock().unwrap() = changed;
        assert!(host.acknowledge_retained_checkpoint().await.is_err());
        assert_eq!(
            host.pending_checkpoint().await.unwrap().receipt,
            pending.receipt
        );
    }
    *registry.plan.lock().unwrap() = original;
    host.acknowledge_retained_checkpoint().await.unwrap();
    assert!(host.pending_checkpoint().await.is_none());
    read(&store, &registry, &host).await.unwrap();
    let retained: Retained =
        serde_json::from_slice(&std::fs::read(&registry.witness).unwrap()).unwrap();
    assert_eq!(retained.sequence, 2);
}

#[tokio::test]
async fn current_model_encoder_graph_or_forget_drift_closes_persistent_agentd_read() {
    let (temp, store, owner, context, _) = super::fixture(193).await;
    let original = plan(&store, &owner, &context).await;
    let registry = Arc::new(TestRegistry {
        owner: owner.clone(),
        plan: Mutex::new(original.clone()),
        context: context.clone(),
        witness: temp.path().join("independent-host-witness.json"),
        bootstrap_allowed: true,
        fail_retention: AtomicBool::new(false),
        retention_gate: Mutex::new(None),
    });
    let (writer, _) = writer(store.clone(), &owner).await;
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    let host = Arc::new(AgentdMemoryCellPersistenceHostV1::new(writer, current).unwrap());
    read(&store, &registry, &host).await.unwrap();
    let before = store.recovery_anchor().await.unwrap();
    for kind in 0..3 {
        let mut changed = original.clone();
        match kind {
            0 => changed.manifest.encoder_digest = fixture_digest(b"wrong-encoder"),
            1 => changed.manifest.shared_base_digest = fixture_digest(b"wrong-base-model"),
            _ => changed.manifest.graph_generation = ContractGenerationV1::new(2).unwrap(),
        }
        *registry.plan.lock().unwrap() = changed;
        assert!(matches!(
            read(&store, &registry, &host).await,
            Err(CognitiveContextError::MemoryCellPersistenceUnavailable)
        ));
        assert_eq!(store.recovery_anchor().await.unwrap(), before);
    }
    *registry.plan.lock().unwrap() = original;
    let support = &context.engram_snapshot.nodes[0].support[0];
    let access = CognitiveAccess::agent_private(owner);
    let memory = store
        .read_memory_head(
            &access,
            &StableMemoryId::parse(support.record_id.as_str()).unwrap(),
        )
        .await
        .unwrap();
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "withdraw persisted recall support".into(),
                valid_from_unix_seconds: crate::cognitive_context::now_seconds().unwrap(),
                citations: memory.citations,
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        read(&store, &registry, &host).await,
        Err(CognitiveContextError::MemoryCellPersistenceUnavailable)
    ));
    let retained: Retained =
        serde_json::from_slice(&std::fs::read(&registry.witness).unwrap()).unwrap();
    assert_eq!(retained.sequence, 1);
}

#[tokio::test]
async fn forget_after_sqlite_commit_before_host_retention_closes_original_response() {
    let (temp, store, owner, context, _) = super::fixture(194).await;
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let registry = Arc::new(TestRegistry {
        owner: owner.clone(),
        plan: Mutex::new(plan(&store, &owner, &context).await),
        context: context.clone(),
        witness: temp.path().join("independent-host-witness.json"),
        bootstrap_allowed: true,
        fail_retention: AtomicBool::new(false),
        retention_gate: Mutex::new(Some(RetentionGate {
            entered: entered_tx,
            release: release_rx,
        })),
    });
    let (writer, _) = writer(store.clone(), &owner).await;
    let current: Arc<dyn CurrentMemoryRetrievalContext> = registry.clone();
    let host = Arc::new(AgentdMemoryCellPersistenceHostV1::new(writer, current).unwrap());
    let reading = {
        let store = store.clone();
        let registry = Arc::clone(&registry);
        let host = Arc::clone(&host);
        tokio::spawn(async move { read(&store, &registry, &host).await })
    };
    tokio::time::timeout(std::time::Duration::from_secs(10), entered_rx)
        .await
        .unwrap()
        .unwrap();
    let pending = host.pending_checkpoint().await.unwrap();
    assert!(pending.recovery_anchor.is_some());
    let support = &context.engram_snapshot.nodes[0].support[0];
    let access = CognitiveAccess::agent_private(owner);
    let memory = store
        .read_memory_head(
            &access,
            &StableMemoryId::parse(support.record_id.as_str()).unwrap(),
        )
        .await
        .unwrap();
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "withdraw during independent witness retention".into(),
                valid_from_unix_seconds: crate::cognitive_context::now_seconds().unwrap(),
                citations: memory.citations,
            },
        )
        .await
        .unwrap();
    release_tx.send(()).unwrap();
    assert!(matches!(
        reading.await.unwrap(),
        Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(
            _
        )))
    ));
    assert!(matches!(
        read(&store, &registry, &host).await,
        Err(CognitiveContextError::MemoryCellPersistenceUnavailable)
    ));
    let retained: Retained =
        serde_json::from_slice(&std::fs::read(&registry.witness).unwrap()).unwrap();
    assert_eq!(retained.checkpoint, pending.receipt.checkpoint_digest);
    assert_eq!(retained.sequence, 1);
}
