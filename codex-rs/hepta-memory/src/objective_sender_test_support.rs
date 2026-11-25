//! Test-only host fixtures. None is a production authority or checkpoint provider.

use super::*;
use crate::CognitiveStore;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use tempfile::TempDir;
use tokio::sync::Notify;

pub(super) const OWNER: u8 = 231;
pub(super) const LEASE: &str = "objective-sender-test-owner";

pub(super) fn authority(owner: &AgentId, owner_epoch: u64) -> ProductionAuthorityLease {
    ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"objective-sender-test-grant"),
        71,
        owner_epoch,
        4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(
            format!("objective-sender-test-token-{owner_epoch}").into_bytes(),
        )
        .expect("test opaque token"),
    )
    .expect("test authority")
}

pub(super) struct TestVerifier {
    pub revoked: AtomicBool,
}

impl TestVerifier {
    pub fn new() -> Self {
        Self {
            revoked: AtomicBool::new(false),
        }
    }
}

impl ProductionAuthorityVerifier for TestVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected: &AgentId,
    ) -> Result<(), String> {
        if self.revoked.load(Ordering::SeqCst) || authority.agent_id != *expected {
            Err("test host rejected authority".to_string())
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum CheckpointMode {
    Accept,
    Refuse,
    Mismatch,
    Hold,
    RevokeAfterAcknowledgement,
}

pub(super) struct TestCheckpoint {
    pub mode: Mutex<CheckpointMode>,
    pub seen: Mutex<Vec<(CognitiveRecoveryAnchor, ObjectiveSenderWriterFence)>>,
    pub entered: Notify,
    pub release: Notify,
    verifier: Arc<TestVerifier>,
}

impl TestCheckpoint {
    pub fn new(verifier: Arc<TestVerifier>) -> Self {
        Self {
            mode: Mutex::new(CheckpointMode::Accept),
            seen: Mutex::new(Vec::new()),
            entered: Notify::new(),
            release: Notify::new(),
            verifier,
        }
    }
}

impl ObjectiveSenderCheckpoint for TestCheckpoint {
    async fn acknowledge_current(
        &self,
        current: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        let mode = *self.mode.lock().expect("test checkpoint mode");
        self.seen
            .lock()
            .expect("test checkpoint records")
            .push((current.clone(), writer.clone()));
        match mode {
            CheckpointMode::Accept => Ok(current.clone()),
            CheckpointMode::Refuse => Err(ObjectiveSenderCheckpointError::Refused),
            CheckpointMode::Mismatch => {
                let mut other = current.clone();
                other.state_digest = Sha256Digest::for_bytes(b"different-current-cut");
                Ok(other)
            }
            CheckpointMode::Hold => {
                self.entered.notify_one();
                self.release.notified().await;
                Ok(current.clone())
            }
            CheckpointMode::RevokeAfterAcknowledgement => {
                self.verifier.revoked.store(true, Ordering::SeqCst);
                Ok(current.clone())
            }
        }
    }
}

pub(super) struct Fixture {
    pub writer: Arc<ProductionDurableWriter>,
    pub store: CognitiveStore,
    pub checkpoint: Arc<TestCheckpoint>,
    pub verifier: Arc<TestVerifier>,
    pub temp: TempDir,
}

impl Fixture {
    pub async fn new() -> Self {
        let temp = TempDir::new().expect("test root");
        let owner = agent_id(OWNER);
        // Explicit fresh test initialization, never a production recovery fallback.
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("test store");
        let verifier = Arc::new(TestVerifier::new());
        let writer = ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority(&owner, 87),
            verifier.clone(),
            LEASE,
            1,
        )
        .await
        .expect("original live writer");
        let checkpoint = Arc::new(TestCheckpoint::new(verifier.clone()));
        Self {
            writer: Arc::new(writer),
            store,
            checkpoint,
            verifier,
            temp,
        }
    }

    pub fn sender(&self) -> ProductionObjectiveSender<TestCheckpoint> {
        self.writer
            .objective_sender(self.checkpoint.clone(), Duration::from_secs(2))
            .expect("original sender capability")
    }
}

pub(super) fn request() -> ObjectiveSenderRequest {
    let original = serde_json::to_string(&serde_json::json!({
        "issuer_id": "objective-sender-test-issuer", "key_epoch": 3,
        "message_id": "objective-sender-test-message", "sequence": 7,
        "expires_at_ms": 4_000_000_000_000_u64, "signature_hex": "ab".repeat(64),
        "body": {
            "spawn_generation": 1, "run_id": "objective-sender-test-run",
            "objective_revision": 5, "source_envelope_json": "{\"original\":\"你好\"}",
            "runtime_body_digest": "11".repeat(32), "preference_state_digest": "22".repeat(32),
            "model_tuple_digest": "33".repeat(32), "prompt_registry_digest": "44".repeat(32),
            "artifact_set_digest": "55".repeat(32), "authority_epoch": 71
        }
    }))
    .expect("original fixture envelope");
    ObjectiveSenderRequest::from_original(
        original,
        ObjectiveSenderOrigin {
            agent_id: agent_id(OWNER),
            spawn_generation: 1,
            request_id: 19,
            expected_peer_uid: 1000,
            expected_peer_pid: 4321,
            endpoint_identity: "/test/original-agentd.sock".to_string(),
        },
    )
    .expect("structural fixture request")
}

pub(super) fn observation(
    kind: ObjectiveSenderObservationKind,
    json: &str,
) -> ObjectiveSenderObservation {
    ObjectiveSenderObservation::from_original(kind, json.to_string()).expect("fixture observation")
}
