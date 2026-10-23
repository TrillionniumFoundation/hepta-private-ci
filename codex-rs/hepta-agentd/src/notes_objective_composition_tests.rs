//! Construction against the original SQLite owner and an explicit protocol
//! fixture. The fixture is not a durable, independent deployment checkpoint.

use super::*;
use crate::AgentdProtectedCheckpointInputs;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointRetainedRequest;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveCheckpointToken;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::ObjectiveSenderCheckpointError;
use pretty_assertions::assert_eq;

struct ConstructionPeer {
    receipt: Mutex<CognitiveCheckpointReceipt>,
    calls: AtomicUsize,
}

impl CognitiveCheckpointTransport for ConstructionPeer {
    async fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let request: CognitiveCheckpointRequest = serde_json::from_slice(bytes).unwrap();
        let mut current = self.receipt.lock().unwrap();
        match request.command {
            CognitiveCheckpointCommand::ReadHead => {}
            CognitiveCheckpointCommand::BeginWrites => {
                assert_eq!(request.expected, Some(current.token.clone()));
                assert_eq!(current.head.phase, CognitiveCheckpointPhase::Current);
                let predecessor_token = current.token.clone();
                current.head.phase = CognitiveCheckpointPhase::Dirty;
                current.head.counter += 1;
                current.head.last_mutation_sequence =
                    u64::from_str_radix(&request.request_id[16..], 16).unwrap();
                current.head.last_request = Some(CognitiveCheckpointRetainedRequest {
                    request_id: request.request_id.clone(),
                    request_sha256: Sha256Digest::for_bytes(bytes),
                    command: request.command,
                    predecessor_token,
                });
                current.token.counter = current.head.counter;
                current.token.head_sha256 =
                    Sha256Digest::for_bytes(&serde_json::to_vec(&current.head).unwrap());
            }
            CognitiveCheckpointCommand::PreparePublication
            | CognitiveCheckpointCommand::CommitPublication
            | CognitiveCheckpointCommand::FencePublisher => {
                return Err(ObjectiveSenderCheckpointError::Refused);
            }
        }
        Ok(serde_json::to_vec(&CognitiveCheckpointResponse {
            schema_version: 1,
            request_id: request.request_id,
            status: CognitiveCheckpointStatus::Ack,
            reason: None,
            token: Some(current.token.clone()),
            head: Some(current.head.clone()),
        })
        .unwrap())
    }
}

#[tokio::test]
async fn notes_objective_protected_factory_checks_complete_binding_before_recovery_and_reuses_owner()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        operations,
        ..
    } = notes_host_fixture().await?;
    let runtime = host.cognitive_runtime();
    let store = runtime.available_store().unwrap();
    let cut = store.recovery_anchor().await?;
    let authority = operations.authority;
    let verifier = operations.verifier;
    let head = CognitiveCheckpointHead {
        schema_version: 1,
        owner_agent_id: authority.agent_id.clone(),
        publisher_epoch: 1,
        counter: 1,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: operations.lease_id.clone(),
            generation: operations.lease_generation,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest()?,
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        },
        peer_lifetime: CognitiveCheckpointPeerLifetime {
            uid: 1,
            pid: 1,
            boot_id: "construction-test-peer".into(),
            process_start_ticks: 1,
        },
        phase: CognitiveCheckpointPhase::Current,
        last_current: cut.clone(),
        proposal: None,
        last_request: None,
    };
    let receipt = CognitiveCheckpointReceipt {
        token: CognitiveCheckpointToken {
            publisher_epoch: head.publisher_epoch,
            counter: head.counter,
            head_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(&head)?),
        },
        head,
    };
    let peer = Arc::new(ConstructionPeer {
        receipt: Mutex::new(receipt.clone()),
        calls: AtomicUsize::new(0),
    });
    for field in 0..10 {
        let mut changed = receipt.clone();
        let binding = &mut changed.head.writer_binding;
        match field {
            0 => binding.lease_id.push('x'),
            1 => binding.generation += 1,
            2 => binding.authority_epoch += 1,
            3 => binding.owner_epoch += 1,
            4 => binding.authority_grant_digest = Sha256Digest::for_bytes(b"wrong grant"),
            5 => binding.fencing_token_digest = Sha256Digest::for_bytes(b"wrong token"),
            6 => binding.expires_at_unix_seconds += 1,
            7 => {
                changed.head.owner_agent_id =
                    AgentId::parse("00000000-0000-4000-8000-00000000c062")?
            }
            8 => changed.head.phase = CognitiveCheckpointPhase::Dirty,
            9 => changed.head.phase = CognitiveCheckpointPhase::Fenced,
            _ => unreachable!(),
        }
        let result = AgentdProductionWriterHost::open_with_protected_recovery(
            &config,
            authority.clone(),
            verifier.clone(),
            operations.lease_id.clone(),
            operations.lease_generation,
            AgentdProtectedCheckpointInputs {
                transport: peer.clone(),
                current_receipt: changed,
                deadline: Duration::from_secs(2),
            },
        )
        .await;
        assert!(matches!(result, Err(AgentdError::GenerationFenced(_))));
    }
    assert_eq!(peer.calls.load(Ordering::SeqCst), 0);
    assert_eq!(store.recovery_anchor().await?, cut);
    store.as_ref().clone().close().await;
    drop(runtime);
    drop(host);
    let (host, checkpoint) = AgentdProductionWriterHost::open_with_protected_recovery(
        &config,
        authority,
        verifier,
        operations.lease_id,
        operations.lease_generation,
        AgentdProtectedCheckpointInputs {
            transport: peer.clone(),
            current_receipt: receipt,
            deadline: Duration::from_secs(2),
        },
    )
    .await?;
    assert_eq!(host.writer().owner_agent_id(), &config.identity().agent_id);
    assert_eq!(
        peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    let host = Arc::new(host);
    let config = config.with_production_writer_host(host.clone())?;
    let _sender = config.original_objective_sender(checkpoint, Duration::from_secs(2))?;
    host.writer()
        .admit("composition-proof", "test", "{}")
        .await?;
    // The original writer's one admission is visible through its read side;
    // there was no second owner opened for the runtime or the sender.
    assert_ne!(
        host.cognitive_runtime()
            .available_store()
            .unwrap()
            .recovery_anchor()
            .await?,
        cut
    );
    Ok(())
}
