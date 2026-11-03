//! Real Unix-control publication with client-local request counters. Empty
//! Memory still exercises the native HNMF abstention and witnessed Ledger path.

use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::RetrievalPublicationStateV2;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdClient;
use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::CurrentMemoryRetrievalContext;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::cognitive_context_delivery::encode_control_frame;

use super::digest;
use super::id;
use super::owner;
use super::sink;

struct NativeCurrentContext {
    owner: AgentId,
    context: RetrievalExecutionContextV1,
}

impl CurrentMemoryRetrievalContext for NativeCurrentContext {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != 1 {
            return Err("retrieval context belongs to another Agentd body".to_string());
        }
        self.context.validate().map_err(|error| error.to_string())?;
        Ok(self.context.clone())
    }
}

#[tokio::test]
async fn cognitive_publication_socket_reused_client_request_ids_bind_exact_confirmed_frames() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let registry = FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = registry
        .register(
            AgentManifest::new(
                owner(),
                WorkspaceBinding::new(workspace.clone(), &fleet_root).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    registry
        .compare_and_transition(
            &owner(),
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .unwrap();
    let config = AgentdConfig::load(
        fleet_path,
        owner(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let store = Arc::new(CognitiveStore::open(&record.layout).await.unwrap());
    let now = i64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs(),
    )
    .unwrap();
    let cut = store
        .lane_c_snapshot(
            &CognitiveAccess::agent_private(owner()),
            &CognitiveScope::AgentPrivate,
            now,
        )
        .await
        .unwrap();
    let retrieval_policy = sqlite_owner_retrieval_policy_v1().unwrap();
    let external = digest("publication-socket-external-generations");
    let generation_vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: id("purpose:agentd-hnmf-context"),
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(/*value*/ 1).unwrap(),
        prompt_registry_revision: Revision::new(/*value*/ 1).unwrap(),
        retrieval_profile_digest: retrieval_policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let engram_snapshot = EngramSnapshotV1::new(
        generation_vector.digest(),
        digest("publication-socket-engram-generation"),
        Vec::new(),
        Vec::new(),
    )
    .unwrap();
    let context = RetrievalExecutionContextV1 {
        generation_vector,
        objective_digest: digest("retrieve relevant verified memory"),
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy,
        engram_snapshot,
        dynamics_policy: EngramDynamicsPolicyV1::product_default().unwrap(),
    };
    context.validate().unwrap();
    let current: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(NativeCurrentContext {
        owner: owner(),
        context,
    });
    let (_ledger_directory, learning) = sink();
    let learning = Arc::new(learning);
    let config = config
        .with_cognitive_retrieval_context(current)
        .unwrap()
        .with_cognitive_retrieval_learning(Arc::clone(&learning))
        .unwrap();
    let current = config.cognitive_retrieval_context().unwrap();
    let attached_learning = config.cognitive_retrieval_learning().unwrap();
    let (identity, registry, _writer_lock) = config.into_parts();
    let socket = identity.control_socket.clone();
    let state =
        Arc::new(AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).unwrap());
    state.attach_cognitive_store(store).unwrap();
    state.mark_runtime_prerequisites_ready().unwrap();
    assert!(state.cognitive_retrieval_context.set(current).is_ok());
    assert!(
        state
            .cognitive_retrieval_learning
            .set(attached_learning)
            .is_ok()
    );
    registry
        .compare_and_transition(
            &owner(),
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .unwrap();
    state.mark_app_server_ready().unwrap();

    // Preparing a response without a transport must assert no publication fact.
    let prepared = state
        .response(
            /*request_id*/ 44,
            /*spawn_generation*/ 1,
            AgentdMethod::CognitiveContext {
                query: "prepared only".to_string(),
                limit: 4,
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        prepared.payload,
        AgentdPayload::CognitiveContext(_)
    ));
    assert!(
        learning
            .writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .is_empty()
    );

    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server =
        AgentdControlServer::bind(socket.clone(), Arc::clone(&state), cancellation.clone())
            .await
            .unwrap();
    let task = tokio::spawn(server.run());
    // Neither client performs a preceding health/capabilities call: both first
    // CognitiveContext requests really use their independent counter value 1.
    let first_client = AgentdClient::new(socket.clone(), owner(), /*spawn_generation*/ 1).unwrap();
    let second_client = AgentdClient::new(socket.clone(), owner(), /*spawn_generation*/ 1).unwrap();
    let first = first_client
        .cognitive_context("first empty query".to_string(), /*limit*/ 4)
        .await
        .unwrap();
    let second = second_client
        .cognitive_context("second empty query".to_string(), /*limit*/ 4)
        .await
        .unwrap();
    let mut received = Vec::new();
    for snapshot in [first, second] {
        assert!(snapshot.items.is_empty());
        assert!(!snapshot.plan.as_ref().unwrap().read_allowed);
        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: owner(),
            spawn_generation: 1,
            current_generation: 2,
            payload: AgentdPayload::CognitiveContext(snapshot.clone()),
        };
        received.push((encode_control_frame(&response).unwrap(), snapshot));
    }

    // Capture a third actual complete frame, including newline and EOF, rather
    // than relying only on reserialization of the clients' parsed snapshots.
    let mut stream = UnixStream::connect(&socket).await.unwrap();
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        spawn_generation: 1,
        method: AgentdMethod::CognitiveContext {
            query: "raw empty query".to_string(),
            limit: 4,
        },
    };
    stream
        .write_all(&encode_control_frame(&request).unwrap())
        .await
        .unwrap();
    let mut reader = BufReader::new(stream).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = timeout(Duration::from_secs(2), reader.read_until(b'\n', &mut frame))
        .await
        .unwrap()
        .unwrap();
    assert!(count > 0 && count as u64 <= MAX_CONTROL_FRAME_BYTES && frame.ends_with(b"\n"));
    let response: AgentdResponse = serde_json::from_slice(&frame).unwrap();
    assert_eq!(response.request_id, 1);
    assert_eq!(response.agent_id, owner());
    assert_eq!(response.spawn_generation, 1);
    assert_eq!(response.current_generation, 2);
    let AgentdPayload::CognitiveContext(snapshot) = response.payload else {
        panic!("real control response did not contain the prepared context");
    };
    let mut trailing = Vec::new();
    timeout(Duration::from_secs(2), reader.read_to_end(&mut trailing))
        .await
        .unwrap()
        .unwrap();
    assert!(
        trailing.is_empty(),
        "the transport must publish exactly one frame"
    );
    received.push((frame, snapshot));

    // The normal client returns after its frame arrives; confirmation can still
    // be syncing. Observe the real writer with a bounded wait for that boundary.
    timeout(Duration::from_secs(2), async {
        loop {
            let confirmed = learning
                .writer
                .lock()
                .unwrap()
                .snapshot()
                .unwrap()
                .records()
                .iter()
                .filter(|record| {
                    matches!(
                        record.event,
                        LedgerEvent::RetrievalPublicationConfirmedV2(_)
                    )
                })
                .count();
            if confirmed == received.len() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .unwrap();
    {
        let writer = learning.writer.lock().unwrap();
        let ledger = writer.snapshot().unwrap();
        assert_eq!(ledger.records().len(), received.len() * 2);
        assert!(ledger.records().iter().all(|record| matches!(
            record.event,
            LedgerEvent::RetrievalAssignmentIntentV2(_)
                | LedgerEvent::RetrievalPublicationConfirmedV2(_)
        )));
        let intents = ledger
            .records()
            .iter()
            .filter_map(|record| {
                if let LedgerEvent::RetrievalAssignmentIntentV2(intent) = &record.event {
                    Some((record, intent))
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        assert_eq!(intents.len(), received.len());
        assert_ne!(intents[0].1.record_id, intents[1].1.record_id);
        assert_ne!(intents[0].1.cue_digest, intents[1].1.cue_digest);
        for (frame, snapshot) in received {
            let frame_digest = Digest32::of_bytes(&frame);
            let (record, intent) = intents
                .iter()
                .copied()
                .find(|(_, intent)| intent.response_frame_digest == frame_digest)
                .unwrap();
            assert_eq!(intent.owner_id, id(owner().as_str()));
            assert_eq!(intent.body_generation, 1);
            assert_eq!(intent.request_id, 1);
            assert_eq!(intent.response_frame_bytes as usize, frame.len());
            assert_eq!(
                intent.snapshot_digest,
                Digest32::of_bytes(&serde_json::to_vec(&snapshot).unwrap())
            );
            assert!(intent.planned_candidate_indices.is_empty());
            let projection = writer
                .retrieval_publication(&intent.record_id)
                .unwrap()
                .unwrap();
            assert_eq!(
                projection.state,
                RetrievalPublicationStateV2::HostTransportWriteCompleted
            );
            assert_eq!(projection.intent_event_digest, Some(record.event_digest));
            assert!(projection.confirmation_event_digest.is_some());
            assert!(projection.ledger_lineage_active);
        }
    }

    // Exhaust the real sink reservations before any blocking append can start.
    // The socket sends one typed error frame, never the prepared success frame.
    let reservations = (0..32)
        .map(|_| learning.reserve_publication().unwrap())
        .collect::<Vec<_>>();
    assert!(learning.reserve_publication().is_err());
    let mut stream = UnixStream::connect(&socket).await.unwrap();
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 93,
        spawn_generation: 1,
        method: AgentdMethod::CognitiveContext {
            query: "capacity rejected query".to_string(),
            limit: 4,
        },
    };
    stream
        .write_all(&encode_control_frame(&request).unwrap())
        .await
        .unwrap();
    let mut reader = BufReader::new(stream).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut rejected_frame = Vec::new();
    let count = timeout(
        Duration::from_secs(2),
        reader.read_until(b'\n', &mut rejected_frame),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(
        count > 0 && count as u64 <= MAX_CONTROL_FRAME_BYTES && rejected_frame.ends_with(b"\n")
    );
    let rejected: AgentdResponse = serde_json::from_slice(&rejected_frame).unwrap();
    assert_eq!(rejected.request_id, 93);
    assert_eq!(rejected.agent_id, owner());
    assert_eq!(rejected.spawn_generation, 1);
    assert!(matches!(
        rejected.payload,
        AgentdPayload::Error { code, .. }
            if code == "cognitive_retrieval_learning_unavailable"
    ));
    let mut trailing = Vec::new();
    timeout(Duration::from_secs(2), reader.read_to_end(&mut trailing))
        .await
        .unwrap()
        .unwrap();
    assert!(trailing.is_empty());
    assert_eq!(
        learning
            .writer
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .len(),
        6
    );
    drop(reservations);

    // Capacity is available again. Commit an actual bounded success-frame
    // intent, then change the real Fleet lifecycle before the transport gate.
    let mut late = state
        .prepare_response(
            /*request_id*/ 94,
            /*spawn_generation*/ 1,
            AgentdMethod::CognitiveContext {
                query: "late lifecycle query".to_string(),
                limit: 4,
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        late.response.payload,
        AgentdPayload::CognitiveContext(_)
    ));
    let frame = encode_control_frame(&late.response).unwrap();
    let publication = late.context.as_mut().unwrap();
    let confirmation = publication
        .begin_intent(
            &owner(),
            /*body_generation*/ 1,
            /*request_id*/ 94,
            &frame,
        )
        .await
        .unwrap()
        .unwrap();
    registry
        .compare_and_transition(
            &owner(),
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .unwrap();
    let (transport, mut peer) = tokio::io::duplex(MAX_CONTROL_FRAME_BYTES as usize);
    assert!(
        state
            .revalidate_control_publication(&late.response, publication)
            .await
            .is_err()
    );
    state.retract_control_publication(&late.response);
    drop(confirmation);
    drop(transport);
    let mut unpublished = Vec::new();
    peer.read_to_end(&mut unpublished).await.unwrap();
    assert!(unpublished.is_empty());
    {
        let writer = learning.writer.lock().unwrap();
        let ledger = writer.snapshot().unwrap();
        assert_eq!(ledger.records().len(), 7);
        assert_eq!(
            ledger
                .records()
                .iter()
                .filter(|record| matches!(
                    record.event,
                    LedgerEvent::RetrievalPublicationConfirmedV2(_)
                ))
                .count(),
            3
        );
        let intent = ledger
            .records()
            .iter()
            .find_map(|record| {
                if let LedgerEvent::RetrievalAssignmentIntentV2(intent) = &record.event
                    && intent.response_frame_digest == Digest32::of_bytes(&frame)
                {
                    Some(intent)
                } else {
                    None
                }
            })
            .unwrap();
        let projection = writer
            .retrieval_publication(&intent.record_id)
            .unwrap()
            .unwrap();
        assert_eq!(projection.state, RetrievalPublicationStateV2::Unknown);
        assert!(projection.confirmation_event_digest.is_none());
        assert!(!projection.ledger_lineage_active);
    }
    cancellation.cancel();
    task.await.unwrap().unwrap();
}
