#![cfg(unix)]

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::backend::AuthenticatedRuntimeStatus;
use hepta_native::backend::BackendAdapter;
use hepta_native::error::ShellError;
use hepta_native::journal::OperationJournal;
use hepta_native::model::EndpointManifest;
use hepta_native::model::PlatformObservation;
use hepta_native::model::PlatformPayload;
use hepta_native::model::PlatformRequest;
use hepta_native::model::RuntimeView;
use hepta_native::model::SessionIncarnation;
use hepta_native::model::TerminalStatus;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;
use hepta_native::security::KernelFinalUseGate;
use hepta_native::security::now_unix_ms;
use hepta_native::security::platform_final_use_binding;
use tempfile::TempDir;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";
const SUBJECT: &str = "principal.1";
const SIGNER: &str = "authority.native";

#[derive(Debug)]
struct MockBackend {
    sessions: VecDeque<SessionIncarnation>,
}

impl BackendAdapter for MockBackend {
    fn connect(&mut self, _manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        self.sessions
            .pop_front()
            .ok_or_else(|| ShellError::Backend("no mock session".to_owned()))
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        Ok(AuthenticatedRuntimeStatus {
            value: serde_json::json!({
                "status": "ok",
                "state": {"runtime_snapshot_generation": 7}
            }),
            body_digest: D2.to_owned(),
        })
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
}

#[derive(Debug)]
struct PlatformState {
    invoke_calls: usize,
    reconcile_calls: usize,
    invoke_indeterminate: bool,
    reconcile_terminal: bool,
    permission_allowed: bool,
}

impl Default for PlatformState {
    fn default() -> Self {
        Self {
            invoke_calls: 0,
            reconcile_calls: 0,
            invoke_indeterminate: false,
            reconcile_terminal: false,
            permission_allowed: true,
        }
    }
}

#[derive(Debug, Clone)]
struct MockPlatform {
    state: Arc<Mutex<PlatformState>>,
}

impl PlatformAdapter for MockPlatform {
    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        Ok(PermissionDecision {
            allowed: self.state.lock().unwrap().permission_allowed,
            outcome_digest: D1.to_owned(),
        })
    }

    fn invoke(
        &mut self,
        _key: &hepta_native::model::OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        let mut state = self.state.lock().unwrap();
        state.invoke_calls += 1;
        if state.invoke_indeterminate {
            Ok(PlatformObservation::indeterminate())
        } else {
            Ok(PlatformObservation {
                terminal_status: Some(TerminalStatus::Succeeded),
                outcome_digest: Some(D2.to_owned()),
            })
        }
    }

    fn reconcile(
        &mut self,
        _record: &hepta_native::journal::OperationRecord,
    ) -> Result<PlatformObservation, ShellError> {
        let mut state = self.state.lock().unwrap();
        state.reconcile_calls += 1;
        if state.reconcile_terminal {
            Ok(PlatformObservation {
                terminal_status: Some(TerminalStatus::Succeeded),
                outcome_digest: Some(D2.to_owned()),
            })
        } else {
            Ok(PlatformObservation::indeterminate())
        }
    }
}

fn manifest() -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.1".to_owned(),
        address: "127.0.0.1:7373".to_owned(),
        manifest_digest: D1.to_owned(),
        protocol_version: 1,
    }
}

fn write_authority_config(
    temp: &TempDir,
    signing: &SigningKey,
    head: &FinalUseRevocations,
) -> std::path::PathBuf {
    let path = temp.path().join("final-use-authority.json");
    let state_dir = temp.path().join("final-use-state");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({
            "schema": "hepta.native-final-use-authority.v1",
            "signer_id": SIGNER,
            "verifying_key_base64": STANDARD.encode(signing.verifying_key().to_bytes()),
            "state_dir": state_dir,
            "head": head,
        }))
        .unwrap(),
    )
    .unwrap();
    path
}

fn authority_fixture(temp: &TempDir) -> (Arc<KernelFinalUseGate>, SigningKey, std::path::PathBuf) {
    let signing = SigningKey::from_bytes(&[7_u8; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let config = write_authority_config(temp, &signing, &head);
    let gate = Arc::new(KernelFinalUseGate::open(config.clone()).unwrap());
    (gate, signing, config)
}

fn signed_grant(
    signing: &SigningKey,
    session: &SessionIncarnation,
    operation_id: &str,
    displayed_revision: u64,
    payload: &PlatformPayload,
    nonce_byte: u8,
) -> SignedFinalUseGrant {
    let binding =
        platform_final_use_binding(SUBJECT, session, operation_id, displayed_revision, payload)
            .unwrap();
    let now = now_unix_ms().unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: SIGNER.to_owned(),
        authority_epoch: 1,
        grant_id: format!("grant.{nonce_byte}"),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn request(
    signing: &SigningKey,
    session: &SessionIncarnation,
    operation_id: &str,
    displayed_revision: u64,
    payload: PlatformPayload,
    nonce_byte: u8,
) -> PlatformRequest {
    PlatformRequest {
        subject_id: SUBJECT.to_owned(),
        operation_id: operation_id.to_owned(),
        displayed_revision,
        grant: signed_grant(
            signing,
            session,
            operation_id,
            displayed_revision,
            &payload,
            nonce_byte,
        ),
        payload,
    }
}

fn render(runtime: &mut NativeShellRuntime, revision: u64) {
    let session = runtime.session().unwrap().clone();
    runtime
        .render_runtime_view(RuntimeView {
            session_id: session.session_id,
            session_generation: session.generation,
            generation: 1,
            revision,
            digest: D2.to_owned(),
            modules: vec![],
        })
        .unwrap();
}

fn runtime_fixture(
    temp: &TempDir,
    sessions: Vec<SessionIncarnation>,
    platform_state: Arc<Mutex<PlatformState>>,
    final_use: Arc<KernelFinalUseGate>,
) -> NativeShellRuntime {
    NativeShellRuntime::new(
        Box::new(MockBackend {
            sessions: sessions.into(),
        }),
        Box::new(MockPlatform {
            state: platform_state,
        }),
        Some(final_use),
        OperationJournal::open(temp.path().join("operations.json")).unwrap(),
    )
}

#[test]
fn authenticated_backend_status_owns_view_identity() {
    let temp = TempDir::new().unwrap();
    let (final_use, _, _) = authority_fixture(&temp);
    let platform_state = Arc::new(Mutex::new(PlatformState::default()));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.authenticated-view".to_owned(),
        generation: 11,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state, final_use);
    runtime.connect_runtime(&manifest()).unwrap();

    let (presentation, status) = runtime.refresh_runtime_view().unwrap();
    assert_eq!(presentation.session_generation, 11);
    assert_eq!(presentation.generation, 7);
    assert_eq!(presentation.revision, 1);
    assert_eq!(presentation.digest, D2);
    assert_eq!(status["state"]["runtime_snapshot_generation"], 7);

    let (second, _) = runtime.refresh_runtime_view().unwrap();
    assert_eq!(second.generation, 7);
    assert_eq!(second.revision, 2);
    assert_eq!(second.digest, D2);
}

#[test]
fn operation_identity_is_fenced_by_session_incarnation() {
    let temp = TempDir::new().unwrap();
    let (final_use, signing, _) = authority_fixture(&temp);
    let platform_state = Arc::new(Mutex::new(PlatformState::default()));
    let session1 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    let session2 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.2".to_owned(),
        generation: 2,
    };
    let mut runtime = runtime_fixture(
        &temp,
        vec![session1, session2],
        platform_state.clone(),
        final_use,
    );
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let payload = PlatformPayload::CopyText {
        text: "one".to_owned(),
    };
    let first_session = runtime.session().unwrap().clone();
    let first = runtime
        .request_platform_capability(request(
            &signing,
            &first_session,
            "operation.1",
            1,
            payload.clone(),
            1,
        ))
        .unwrap();
    assert!(first.terminal_observed);

    runtime.close().unwrap();
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let second_session = runtime.session().unwrap().clone();
    let second = runtime
        .request_platform_capability(request(
            &signing,
            &second_session,
            "operation.1",
            1,
            payload,
            2,
        ))
        .unwrap();
    assert!(second.terminal_observed);
    assert_ne!(first.key.session_id, second.key.session_id);
    assert_eq!(platform_state.lock().unwrap().invoke_calls, 2);
    assert_eq!(runtime.operation_history().len(), 2);
}

#[test]
fn indeterminate_retry_reconciles_instead_of_replaying_or_reclaiming() {
    let temp = TempDir::new().unwrap();
    let (final_use, signing, _) = authority_fixture(&temp);
    let platform_state = Arc::new(Mutex::new(PlatformState {
        invoke_indeterminate: true,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state.clone(), final_use);
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "payload".to_owned(),
    };
    let original = request(&signing, &session, "operation.2", 1, payload, 3);
    let first = runtime
        .request_platform_capability(original.clone())
        .unwrap();
    assert!(!first.terminal_observed);

    platform_state.lock().unwrap().reconcile_terminal = true;
    let second = runtime.request_platform_capability(original).unwrap();
    assert!(second.terminal_observed);
    let state = platform_state.lock().unwrap();
    assert_eq!(state.invoke_calls, 1);
    assert_eq!(state.reconcile_calls, 1);
}

#[test]
fn restart_reconciles_old_indeterminate_without_reinvoke() {
    let temp = TempDir::new().unwrap();
    let signing = SigningKey::from_bytes(&[7_u8; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let config = write_authority_config(&temp, &signing, &head);
    let first_state = Arc::new(Mutex::new(PlatformState {
        invoke_indeterminate: true,
        ..Default::default()
    }));
    let session1 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    {
        let gate = Arc::new(KernelFinalUseGate::open(config.clone()).unwrap());
        let mut runtime = runtime_fixture(&temp, vec![session1], first_state.clone(), gate);
        runtime.connect_runtime(&manifest()).unwrap();
        render(&mut runtime, 1);
        let session = runtime.session().unwrap().clone();
        let payload = PlatformPayload::CopyText {
            text: "uncertain".to_owned(),
        };
        let receipt = runtime
            .request_platform_capability(request(
                &signing,
                &session,
                "operation.restart",
                1,
                payload,
                4,
            ))
            .unwrap();
        assert!(!receipt.terminal_observed);
    }

    let second_state = Arc::new(Mutex::new(PlatformState {
        reconcile_terminal: true,
        ..Default::default()
    }));
    let session2 = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.2".to_owned(),
        generation: 2,
    };
    let gate = Arc::new(KernelFinalUseGate::open(config).unwrap());
    let mut restarted = runtime_fixture(&temp, vec![session2], second_state.clone(), gate);
    restarted.connect_runtime(&manifest()).unwrap();
    let history = restarted.operation_history();
    assert_eq!(history.len(), 1);
    assert!(history[0].terminal_observed);
    let state = second_state.lock().unwrap();
    assert_eq!(state.invoke_calls, 0);
    assert_eq!(state.reconcile_calls, 1);
}

#[test]
fn close_does_not_erase_unobserved_effects() {
    let temp = TempDir::new().unwrap();
    let (final_use, signing, _) = authority_fixture(&temp);
    let platform_state = Arc::new(Mutex::new(PlatformState {
        invoke_indeterminate: true,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state, final_use);
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "uncertain".to_owned(),
    };
    runtime
        .request_platform_capability(request(
            &signing,
            &session,
            "operation.close",
            1,
            payload,
            5,
        ))
        .unwrap();
    runtime.close().unwrap();
    assert_eq!(runtime.pending_operations().len(), 1);
}

#[test]
fn permission_denial_is_terminal_and_never_claims_or_invokes() {
    let temp = TempDir::new().unwrap();
    let (final_use, signing, _) = authority_fixture(&temp);
    let platform_state = Arc::new(Mutex::new(PlatformState {
        permission_allowed: false,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.permission".to_owned(),
        generation: 1,
    };
    let mut runtime =
        runtime_fixture(&temp, vec![session], platform_state.clone(), final_use);
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "denied".to_owned(),
    };
    let receipt = runtime
        .request_platform_capability(request(
            &signing,
            &session,
            "operation.denied",
            1,
            payload,
            6,
        ))
        .unwrap();
    assert!(receipt.terminal_observed);
    assert_eq!(receipt.terminal_status, Some(TerminalStatus::Rejected));
    assert_eq!(platform_state.lock().unwrap().invoke_calls, 0);
}

#[test]
fn missing_kernel_authority_fails_closed_before_adapter_entry() {
    let temp = TempDir::new().unwrap();
    let signing = SigningKey::from_bytes(&[7_u8; 32]);
    let platform_state = Arc::new(Mutex::new(PlatformState::default()));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.no-authority".to_owned(),
        generation: 1,
    };
    let mut runtime = NativeShellRuntime::new(
        Box::new(MockBackend {
            sessions: vec![session].into(),
        }),
        Box::new(MockPlatform {
            state: platform_state.clone(),
        }),
        None,
        OperationJournal::open(temp.path().join("operations.json")).unwrap(),
    );
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let receipt = runtime
        .request_platform_capability(request(
            &signing,
            &session,
            "operation.no-authority",
            1,
            PlatformPayload::CopyText {
                text: "blocked".to_owned(),
            },
            7,
        ))
        .unwrap();
    assert_eq!(receipt.terminal_status, Some(TerminalStatus::Rejected));
    assert_eq!(platform_state.lock().unwrap().invoke_calls, 0);
}
