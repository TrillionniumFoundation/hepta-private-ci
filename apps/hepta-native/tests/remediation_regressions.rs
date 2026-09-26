mod common;

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use common::private_tempdir;
use hepta_native::backend::AuthenticatedRuntimeStatus;
use hepta_native::backend::BackendAdapter;
use hepta_native::error::ShellError;
use hepta_native::journal::OperationJournal;
use hepta_native::journal::OperationRecord;
use hepta_native::model::EndpointManifest;
use hepta_native::model::OperationKey;
use hepta_native::model::PlatformObservation;
use hepta_native::model::PlatformPayload;
use hepta_native::model::PlatformRequest;
use hepta_native::model::SessionIncarnation;
use hepta_native::model::TerminalStatus;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;

const DIGEST: &str = "1111111111111111111111111111111111111111111111111111111111111111";

#[derive(Default)]
struct State {
    close_fails: bool,
    closes: usize,
    connects: usize,
    permission_fails: bool,
    invalid_permission_digest: bool,
    permission_calls: usize,
    invoke_calls: usize,
}

struct Backend {
    state: Arc<Mutex<State>>,
    generations: VecDeque<u64>,
    wrong_endpoint: bool,
}

impl BackendAdapter for Backend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        let mut state = self.state.lock().unwrap();
        state.connects += 1;
        Ok(SessionIncarnation {
            endpoint_id: if self.wrong_endpoint {
                "another.endpoint".to_owned()
            } else {
                manifest.endpoint_id.clone()
            },
            session_id: format!("session.{}", state.connects),
            generation: state.connects as u64,
        })
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        Ok(AuthenticatedRuntimeStatus {
            value: serde_json::json!({
                "state": {"runtime_snapshot_generation": self.generations.pop_front().unwrap()}
            }),
            body_digest: DIGEST.to_owned(),
        })
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        let mut state = self.state.lock().unwrap();
        state.closes += 1;
        if state.close_fails {
            return Err(ShellError::Backend("injected close failure".to_owned()));
        }
        Ok(())
    }
}

struct Platform {
    state: Arc<Mutex<State>>,
    journal_path: PathBuf,
}

impl PlatformAdapter for Platform {
    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        // Read the actual durable file, not the runtime's in-memory vector.
        let value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&self.journal_path).unwrap()).unwrap();
        assert_eq!(value["operations"][0]["phase"], "prepared");
        let mut state = self.state.lock().unwrap();
        state.permission_calls += 1;
        if state.permission_fails {
            return Err(ShellError::Platform("injected permission failure".to_owned()));
        }
        Ok(PermissionDecision {
            allowed: false,
            outcome_digest: if state.invalid_permission_digest {
                "invalid".to_owned()
            } else {
                DIGEST.to_owned()
            },
        })
    }

    fn invoke(
        &mut self,
        _key: &OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        self.state.lock().unwrap().invoke_calls += 1;
        panic!("denied permission must never dispatch a platform effect");
    }

    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        Ok(PlatformObservation::indeterminate())
    }
}

fn manifest() -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.test".to_owned(),
        address: "127.0.0.1:7373".to_owned(),
        manifest_digest: DIGEST.to_owned(),
        protocol_version: 2,
    }
}

fn runtime(
    path: PathBuf,
    state: Arc<Mutex<State>>,
    generations: Vec<u64>,
    wrong_endpoint: bool,
) -> NativeShellRuntime {
    NativeShellRuntime::new(
        Box::new(Backend {
            state: state.clone(),
            generations: generations.into(),
            wrong_endpoint,
        }),
        Box::new(Platform {
            state,
            journal_path: path.clone(),
        }),
        None,
        OperationJournal::open(path).unwrap(),
    )
}

fn denied_request(runtime: &NativeShellRuntime) -> PlatformRequest {
    let payload = PlatformPayload::CopyText {
        text: "remediation fixture".to_owned(),
    };
    let binding = runtime
        .prepare_platform_binding("subject.test", "operation.test", &payload)
        .unwrap();
    // Deliberately unsigned: these tests must exit before authority admission.
    // Existing runtime/security suites exercise real signature admission.
    PlatformRequest {
        subject_id: "subject.test".to_owned(),
        operation_id: "operation.test".to_owned(),
        displayed_revision: runtime.view().unwrap().revision,
        payload,
        grant: SignedFinalUseGrant {
            grant: FinalUseGrant {
                schema_version: 1,
                signer_id: "untrusted.fixture".to_owned(),
                authority_epoch: 1,
                grant_id: "grant.denied".to_owned(),
                nonce: [1; 32],
                binding,
                not_before_unix_ms: 1,
                expires_at_unix_ms: 2,
            },
            signature: vec![0; 64],
        },
    }
}

#[test]
fn revision_never_aliases_across_upstream_generations() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state,
        vec![7, 8, 9],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    for revision in 1..=3 {
        let (view, _) = shell.refresh_runtime_view().unwrap();
        assert_eq!(view.revision, revision);
        assert_eq!(view.generation, revision + 6);
    }
}

#[test]
fn genesis_zero_remains_compatible_without_revision_aliasing() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(temp.path().join("operations.json"), state, vec![0, 1], false);
    shell.connect_runtime(&manifest()).unwrap();
    let (first, raw) = shell.refresh_runtime_view().unwrap();
    assert_eq!(raw["state"]["runtime_snapshot_generation"], 0);
    let (next, _) = shell.refresh_runtime_view().unwrap();
    assert_eq!(first.revision, 1);
    assert_eq!(next.revision, 2);
}

#[test]
fn raw_generation_regression_is_not_hidden_by_genesis_projection() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(temp.path().join("operations.json"), state, vec![1, 0], false);
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    let error = shell.refresh_runtime_view().unwrap_err();
    assert!(error.to_string().contains("snapshot generation regressed"));
    assert_eq!(shell.view().unwrap().revision, 1);
}

#[test]
fn old_view_cannot_authorize_new_generation_before_permission() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![7, 8],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    let request = denied_request(&shell);
    shell.refresh_runtime_view().unwrap();
    let error = shell.request_platform_capability(request).unwrap_err();
    assert!(error.to_string().contains("stale runtime view"));
    assert_eq!(state.lock().unwrap().permission_calls, 0);
    assert!(shell.operation_history().is_empty());
}

#[test]
fn exact_terminal_duplicate_returns_receipt_after_view_advance() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![7, 8],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    let request = denied_request(&shell);
    let first = shell.request_platform_capability(request.clone()).unwrap();
    shell.refresh_runtime_view().unwrap();
    let duplicate = shell.request_platform_capability(request).unwrap();
    assert_eq!(first, duplicate);
    assert_eq!(first.terminal_status, Some(TerminalStatus::Rejected));
    assert_eq!(state.lock().unwrap().permission_calls, 1);
}

#[test]
fn permission_error_has_durable_immutable_no_dispatch_outcome() {
    let temp = private_tempdir();
    let path = temp.path().join("operations.json");
    let state = Arc::new(Mutex::new(State {
        permission_fails: true,
        ..State::default()
    }));
    let first;
    {
        let mut shell = runtime(path.clone(), state.clone(), vec![7], false);
        shell.connect_runtime(&manifest()).unwrap();
        shell.refresh_runtime_view().unwrap();
        let request = denied_request(&shell);
        first = shell.request_platform_capability(request.clone()).unwrap();
        assert_eq!(first.terminal_status, Some(TerminalStatus::Rejected));
        assert_eq!(first, shell.request_platform_capability(request).unwrap());
    }
    let journal = OperationJournal::open(path).unwrap();
    assert_eq!(journal.all()[0].receipt(), first);
    assert_eq!(state.lock().unwrap().permission_calls, 1);
    assert_eq!(state.lock().unwrap().invoke_calls, 0);
}

#[test]
fn malformed_permission_observation_is_terminal_without_dispatch() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State {
        invalid_permission_digest: true,
        ..State::default()
    }));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![7],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    let request = denied_request(&shell);
    let first = shell.request_platform_capability(request.clone()).unwrap();
    assert_eq!(first.terminal_status, Some(TerminalStatus::Rejected));
    assert_eq!(first, shell.request_platform_capability(request).unwrap());
    assert_eq!(state.lock().unwrap().permission_calls, 1);
    assert_eq!(state.lock().unwrap().invoke_calls, 0);
}

#[test]
fn failed_close_invalidates_session_and_view() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![7],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    state.lock().unwrap().close_fails = true;
    assert!(shell.close().is_err());
    assert!(shell.session().is_none());
    assert!(shell.view().is_none());
}

#[test]
fn failed_reconnect_close_does_not_retain_previous_view() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![7],
        false,
    );
    shell.connect_runtime(&manifest()).unwrap();
    shell.refresh_runtime_view().unwrap();
    state.lock().unwrap().close_fails = true;
    assert!(shell.connect_runtime(&manifest()).is_err());
    assert!(shell.session().is_none());
    assert!(shell.view().is_none());
    assert_eq!(state.lock().unwrap().connects, 1);
}

#[test]
fn rejected_backend_session_is_closed_before_connect_returns() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(State::default()));
    let mut shell = runtime(
        temp.path().join("operations.json"),
        state.clone(),
        vec![],
        true,
    );
    assert!(shell.connect_runtime(&manifest()).is_err());
    assert!(shell.session().is_none());
    assert!(shell.view().is_none());
    assert_eq!(state.lock().unwrap().closes, 1);
}
