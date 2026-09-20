//! Failure injection around the real signed SQLite lifecycle. The separate
//! native product tests exercise the real Agentd/App Server/rollout transport.

use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_app_server_protocol::QueuedSubmission;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::AgentdIdentity;
use crate::AuthBusTextIngress;
use crate::authbus_ingress::authbus_text_claims;
use crate::authbus_ingress::submit;

struct Fixture {
    _temp: tempfile::TempDir,
    state: Arc<AgentdState>,
    registry: FleetRegistry,
    key: SigningKey,
    trust_file: PathBuf,
}

impl Fixture {
    async fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).unwrap();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let manifest = AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(&workspace, &fleet).unwrap(),
            ResourceBudget::local_default(),
        )
        .unwrap();
        let record = registry.register(manifest).unwrap();
        registry
            .compare_and_transition(
                &agent,
                /*expected_generation*/ 0,
                AgentLifecycle::Starting,
            )
            .unwrap();
        registry
            .compare_and_transition(
                &agent,
                /*expected_generation*/ 1,
                AgentLifecycle::Running,
            )
            .unwrap();
        let identity = AgentdIdentity {
            agent_id: agent,
            spawn_generation: 1,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
            layout: record.layout,
        };
        std::fs::set_permissions(&identity.home_root, std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let trust_file = identity.home_root.join("text-trust.json");
        let state =
            Arc::new(AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).unwrap());
        state.refresh_generation().unwrap();
        state.mark_app_server_ready().unwrap();
        let fixture = Self {
            _temp: temp,
            state,
            registry,
            key: SigningKey::from_bytes(&[55; 32]),
            trust_file,
        };
        fixture.trust(/*revoked*/ false);
        let host = TextIngress::open(fixture.state.identity(), fixture.trust_file.clone())
            .await
            .unwrap();
        assert!(fixture.state.authbus.set(Arc::new(host)).is_ok());
        fixture
    }

    fn trust(&self, revoked: bool) {
        let key = self
            .key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let json = serde_json::json!({"schema_version":1,"agent_id":self.state.identity().agent_id.as_str(),
            "issuer_id":"issuer:test","key_epoch":1,"public_key_hex":key,"revoked":revoked,"thread_ids":["thread:test"]});
        std::fs::write(&self.trust_file, serde_json::to_vec(&json).unwrap()).unwrap();
        std::fs::set_permissions(&self.trust_file, std::fs::Permissions::from_mode(0o600)).unwrap();
    }

    fn request(&self, sequence: u64) -> AuthBusTextIngress {
        let mut request = AuthBusTextIngress {
            issuer_id: "issuer:test".into(),
            key_epoch: 1,
            message_id: format!("message:{sequence}"),
            sequence,
            expires_at_ms: now_ms().unwrap() + 300_000,
            signature_hex: String::new(),
            body: AuthBusTextBody {
                spawn_generation: 1,
                thread_id: "thread:test".into(),
                text: "bounded signed text".into(),
            },
        };
        let claims = authbus_text_claims(&self.state.identity().agent_id, &request).unwrap();
        request.signature_hex = self
            .key
            .sign(&claims.signing_bytes())
            .to_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        request
    }

    async fn claim(&self, host: &TextIngress, id: Digest32) -> AuthBusDelivery {
        host.evidence
            .claim_authbus_delivery(
                &host.trust(&self.state).unwrap().issuer().unwrap(),
                AuthBusClaimRequest {
                    delivery_id: id,
                    subject_id: &host.subject,
                    scope_digest: host.scope,
                    worker_id: &StableId::new("fixture:worker").unwrap(),
                    lease_ms: 30_000,
                },
            )
            .await
            .unwrap()
    }
}

struct ReplyLostQueue {
    accepted: Mutex<BTreeMap<String, Vec<UserInput>>>,
    modes: Mutex<Vec<ThreadQueueReconcileMode>>,
    lose_reply: AtomicBool,
}

impl Default for ReplyLostQueue {
    fn default() -> Self {
        Self {
            accepted: Mutex::new(BTreeMap::new()),
            modes: Mutex::new(Vec::new()),
            lose_reply: AtomicBool::new(/*v*/ true),
        }
    }
}

impl TextQueueTransport for ReplyLostQueue {
    async fn reconcile(
        &self,
        params: ThreadQueueReconcileParams,
    ) -> Result<ThreadQueueReconcileResponse, AgentdError> {
        self.modes.lock().unwrap().push(params.mode);
        let mut accepted = self.accepted.lock().unwrap();
        let created = if accepted.contains_key(&params.client_user_message_id) {
            false
        } else if params.mode == ThreadQueueReconcileMode::AllowIfAbsent {
            accepted.insert(params.client_user_message_id.clone(), params.input.clone());
            true
        } else {
            return Ok(ThreadQueueReconcileResponse {
                client_user_message_id: params.client_user_message_id,
                payload_sha256: params.expected_payload_sha256,
                outcome: ThreadQueueReconcileOutcome::Missing,
            });
        };
        if self.lose_reply.swap(/*val*/ false, Ordering::SeqCst) {
            return Err(invalid("reply lost after queue admission"));
        }
        Ok(ThreadQueueReconcileResponse {
            client_user_message_id: params.client_user_message_id.clone(),
            payload_sha256: params.expected_payload_sha256,
            outcome: ThreadQueueReconcileOutcome::Queued {
                queued_submission: QueuedSubmission {
                    id: "queue:test".into(),
                    input: params.input,
                    client_user_message_id: params.client_user_message_id,
                },
                created,
            },
        })
    }
}

#[tokio::test]
async fn lost_queue_reply_recovers_from_sqlite_using_lookup_only_and_exact_receipt() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let queue = ReplyLostQueue::default();
    let first = fixture.claim(&host, id).await;
    deliver(&fixture.state, &host, &queue, first).await.unwrap();
    assert_eq!(
        host.evidence
            .authbus_delivery_status(id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Queued
    );
    tokio::time::sleep(Duration::from_millis(1100)).await;
    // A new handle recovers persisted attempts; the queue's independent state
    // survived the lost reply. No in-process claim is reused as authority.
    let reopened = TextIngress::open(fixture.state.identity(), fixture.trust_file.clone())
        .await
        .unwrap();
    let recovered = fixture.claim(&reopened, id).await;
    assert_eq!(recovered.attempts, 2);
    deliver(&fixture.state, &reopened, &queue, recovered)
        .await
        .unwrap();
    let status = reopened.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (status.state, status.attempts),
        (AuthBusDeliveryState::Acked, 2)
    );
    assert!(status.acknowledgement.is_some());
    assert_eq!(
        *queue.modes.lock().unwrap(),
        vec![
            ThreadQueueReconcileMode::AllowIfAbsent,
            ThreadQueueReconcileMode::ReconcileOnly
        ]
    );
    assert_eq!(queue.accepted.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn abandoned_first_claim_without_admission_is_quarantined_after_lookup_missing() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let issuer = host.trust(&fixture.state).unwrap().issuer().unwrap();
    let first = fixture.claim(&host, id).await;
    // The owner cannot prove whether a previous claimant sent. Persist a retry
    // then require the same conservative lookup used after lease recovery.
    host.evidence
        .retry_authbus_delivery(&issuer, &first.lease, /*delay_ms*/ 0)
        .await
        .unwrap();
    let recovered = fixture.claim(&host, id).await;
    let queue = ReplyLostQueue::default();
    deliver(&fixture.state, &host, &queue, recovered)
        .await
        .unwrap();
    let status = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (status.state, status.acknowledgement),
        (AuthBusDeliveryState::Quarantined, None)
    );
    assert!(queue.accepted.lock().unwrap().is_empty());
}

struct AuthorityChanges<'a>(&'a Fixture);

impl TextQueueTransport for AuthorityChanges<'_> {
    async fn reconcile(
        &self,
        params: ThreadQueueReconcileParams,
    ) -> Result<ThreadQueueReconcileResponse, AgentdError> {
        self.0.trust(/*revoked*/ true);
        Ok(ThreadQueueReconcileResponse {
            client_user_message_id: params.client_user_message_id,
            payload_sha256: params.expected_payload_sha256,
            outcome: ThreadQueueReconcileOutcome::Persisted {
                turn_id: "turn:accepted".into(),
            },
        })
    }
}

#[tokio::test]
async fn revocation_during_queue_request_prevents_success_ack() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    assert!(
        deliver(&fixture.state, &host, &AuthorityChanges(&fixture), delivery)
            .await
            .is_err()
    );
    let status = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (status.state, status.acknowledgement),
        (AuthBusDeliveryState::Quarantined, None)
    );
}

#[tokio::test]
async fn ready_generation_and_owner_private_trust_are_required_before_admission() {
    let fixture = Fixture::new().await;
    let unconfigured = AgentdState::new(
        fixture.state.identity().clone(),
        fixture.registry.clone(),
        /*event_capacity*/ 16,
    )
    .unwrap();
    unconfigured.refresh_generation().unwrap();
    unconfigured.mark_app_server_ready().unwrap();
    assert!(
        submit(&unconfigured, fixture.request(/*sequence*/ 1))
            .await
            .is_err()
    );
    std::fs::set_permissions(&fixture.trust_file, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(
        submit(&fixture.state, fixture.request(/*sequence*/ 1))
            .await
            .is_err()
    );
    fixture.trust(/*revoked*/ false);
    let backup = fixture.trust_file.with_extension("backup");
    std::fs::rename(&fixture.trust_file, &backup).unwrap();
    std::os::unix::fs::symlink(&backup, &fixture.trust_file).unwrap();
    assert!(
        submit(&fixture.state, fixture.request(/*sequence*/ 1))
            .await
            .is_err()
    );
    std::fs::remove_file(&fixture.trust_file).unwrap();
    std::fs::rename(backup, &fixture.trust_file).unwrap();
    fixture
        .registry
        .compare_and_transition(
            &fixture.state.identity().agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .unwrap();
    assert!(
        submit(&fixture.state, fixture.request(/*sequence*/ 1))
            .await
            .is_err()
    );
    let host = attached(&fixture.state).unwrap();
    assert!(
        host.evidence
            .pending_authbus_deliveries(&host.subject, host.scope, /*limit*/ 16)
            .await
            .unwrap()
            .is_empty()
    );
}

struct MismatchedReceipt;

impl TextQueueTransport for MismatchedReceipt {
    async fn reconcile(
        &self,
        params: ThreadQueueReconcileParams,
    ) -> Result<ThreadQueueReconcileResponse, AgentdError> {
        Ok(ThreadQueueReconcileResponse {
            client_user_message_id: params.client_user_message_id.clone(),
            payload_sha256: params.expected_payload_sha256,
            outcome: ThreadQueueReconcileOutcome::Queued {
                queued_submission: QueuedSubmission {
                    id: "queue:wrong-content".into(),
                    client_user_message_id: params.client_user_message_id,
                    input: vec![UserInput::Text {
                        text: "different unsigned content".into(),
                        text_elements: Vec::new(),
                    }],
                },
                created: true,
            },
        })
    }
}

#[tokio::test]
async fn matching_receipt_metadata_with_different_queue_input_never_acknowledges() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    deliver(&fixture.state, &host, &MismatchedReceipt, delivery)
        .await
        .unwrap();
    let status = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (status.state, status.acknowledgement),
        (AuthBusDeliveryState::Quarantined, None)
    );
}
