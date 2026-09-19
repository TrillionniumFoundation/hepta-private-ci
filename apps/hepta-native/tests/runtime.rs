use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

use hepta_native::backend::BackendAdapter;
use hepta_native::error::ShellError;
use hepta_native::journal::OperationJournal;
use hepta_native::model::EndpointManifest;
use hepta_native::model::PlatformObservation;
use hepta_native::model::PlatformPayload;
use hepta_native::model::PlatformRequest;
use hepta_native::model::RuntimeView;
use hepta_native::model::SessionIncarnation;
use hepta_native::model::SignedPlatformGrantV1;
use hepta_native::model::TerminalStatus;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;
use hepta_native::security::GrantVerifier;
use hepta_native::security::PlatformGrantContext;
use tempfile::TempDir;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";

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

    fn runtime_status(&mut self) -> Result<serde_json::Value, ShellError> {
        Ok(serde_json::json!({"status":"ok"}))
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

#[derive(Debug)]
struct AllowGrantVerifier;

impl GrantVerifier for AllowGrantVerifier {
    fn verify_platform_grant(
        &self,
        _grant: &SignedPlatformGrantV1,
        _context: PlatformGrantContext<'_>,
    ) -> Result<(), ShellError> {
        Ok(())
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

fn grant(
    session: &SessionIncarnation,
    operation_id: &str,
    payload: &PlatformPayload,
) -> SignedPlatformGrantV1 {
    SignedPlatformGrantV1 {
        key_id: "test.key".to_owned(),
        session_id: session.session_id.clone(),
        session_generation: session.generation,
        operation_id: operation_id.to_owned(),
        action: payload.action(),
        payload_digest: payload.digest().unwrap(),
        expires_unix_ms: u64::MAX,
        signature_base64: "ignored".to_owned(),
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
) -> NativeShellRuntime {
    NativeShellRuntime::new(
        Box::new(MockBackend {
            sessions: sessions.into(),
        }),
        Box::new(MockPlatform {
            state: platform_state,
        }),
        Arc::new(AllowGrantVerifier),
        OperationJournal::open(temp.path().join("operations.json")).unwrap(),
    )
}

#[test]
fn operation_identity_is_fenced_by_session_incarnation() {
    let temp = TempDir::new().unwrap();
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
    let mut runtime = runtime_fixture(&temp, vec![session1, session2], platform_state.clone());
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let payload = PlatformPayload::CopyText {
        text: "one".to_owned(),
    };
    let first_session = runtime.session().unwrap().clone();
    let first = runtime
        .request_platform_capability(PlatformRequest {
            operation_id: "operation.1".to_owned(),
            displayed_revision: 1,
            grant: grant(&first_session, "operation.1", &payload),
            payload: payload.clone(),
        })
        .unwrap();
    assert!(first.terminal_observed);

    runtime.close().unwrap();
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let second_session = runtime.session().unwrap().clone();
    let second = runtime
        .request_platform_capability(PlatformRequest {
            operation_id: "operation.1".to_owned(),
            displayed_revision: 1,
            grant: grant(&second_session, "operation.1", &payload),
            payload,
        })
        .unwrap();
    assert!(second.terminal_observed);
    assert_ne!(first.key.session_id, second.key.session_id);
    assert_eq!(platform_state.lock().unwrap().invoke_calls, 2);
    assert_eq!(runtime.operation_history().len(), 2);
}

#[test]
fn indeterminate_retry_reconciles_instead_of_replaying() {
    let temp = TempDir::new().unwrap();
    let platform_state = Arc::new(Mutex::new(PlatformState {
        invoke_indeterminate: true,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state.clone());
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "payload".to_owned(),
    };
    let request = || PlatformRequest {
        operation_id: "operation.2".to_owned(),
        displayed_revision: 1,
        grant: grant(&session, "operation.2", &payload),
        payload: payload.clone(),
    };
    let first = runtime.request_platform_capability(request()).unwrap();
    assert!(!first.terminal_observed);

    platform_state.lock().unwrap().reconcile_terminal = true;
    let second = runtime.request_platform_capability(request()).unwrap();
    assert!(second.terminal_observed);
    let state = platform_state.lock().unwrap();
    assert_eq!(state.invoke_calls, 1);
    assert_eq!(state.reconcile_calls, 1);
}

#[test]
fn restart_reconciles_old_indeterminate_without_reinvoke() {
    let temp = TempDir::new().unwrap();
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
        let mut runtime = runtime_fixture(&temp, vec![session1], first_state.clone());
        runtime.connect_runtime(&manifest()).unwrap();
        render(&mut runtime, 1);
        let session = runtime.session().unwrap().clone();
        let payload = PlatformPayload::CopyText {
            text: "uncertain".to_owned(),
        };
        let receipt = runtime
            .request_platform_capability(PlatformRequest {
                operation_id: "operation.restart".to_owned(),
                displayed_revision: 1,
                grant: grant(&session, "operation.restart", &payload),
                payload,
            })
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
    let mut restarted = runtime_fixture(&temp, vec![session2], second_state.clone());
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
    let platform_state = Arc::new(Mutex::new(PlatformState {
        invoke_indeterminate: true,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.1".to_owned(),
        generation: 1,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state);
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "uncertain".to_owned(),
    };
    runtime
        .request_platform_capability(PlatformRequest {
            operation_id: "operation.close".to_owned(),
            displayed_revision: 1,
            grant: grant(&session, "operation.close", &payload),
            payload,
        })
        .unwrap();
    runtime.close().unwrap();
    assert_eq!(runtime.pending_operations().len(), 1);
}

#[test]
fn permission_denial_is_terminal_and_never_invokes_platform() {
    let temp = TempDir::new().unwrap();
    let platform_state = Arc::new(Mutex::new(PlatformState {
        permission_allowed: false,
        ..Default::default()
    }));
    let session = SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: "session.permission".to_owned(),
        generation: 1,
    };
    let mut runtime = runtime_fixture(&temp, vec![session], platform_state.clone());
    runtime.connect_runtime(&manifest()).unwrap();
    render(&mut runtime, 1);
    let session = runtime.session().unwrap().clone();
    let payload = PlatformPayload::CopyText {
        text: "denied".to_owned(),
    };
    let receipt = runtime
        .request_platform_capability(PlatformRequest {
            operation_id: "operation.denied".to_owned(),
            displayed_revision: 1,
            grant: grant(&session, "operation.denied", &payload),
            payload,
        })
        .unwrap();
    assert!(receipt.terminal_observed);
    assert_eq!(receipt.terminal_status, Some(TerminalStatus::Rejected));
    assert_eq!(platform_state.lock().unwrap().invoke_calls, 0);
}
