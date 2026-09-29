//! Failed cleanup retains ownership, but never restores presentation authority.
mod common;

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

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
use hepta_native::model::SessionIncarnation;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::runtime::NativeShellRuntime;

const DIGEST: &str = "1111111111111111111111111111111111111111111111111111111111111111";

#[derive(Default)]
struct BackendState {
    fail_closes: usize,
    connects: usize,
    closes: Vec<SessionIncarnation>,
}

struct Backend {
    state: Arc<Mutex<BackendState>>,
    sessions: VecDeque<SessionIncarnation>,
}

impl BackendAdapter for Backend {
    fn connect(&mut self, _: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        self.state.lock().unwrap().connects += 1;
        self.sessions
            .pop_front()
            .ok_or_else(|| ShellError::Backend("unexpected connect".to_owned()))
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        Ok(AuthenticatedRuntimeStatus {
            value: serde_json::json!({"state": {"runtime_snapshot_generation": 7}}),
            body_digest: DIGEST.to_owned(),
        })
    }

    fn close(&mut self, session: &SessionIncarnation) -> Result<(), ShellError> {
        let mut state = self.state.lock().unwrap();
        state.closes.push(session.clone());
        if state.fail_closes > 0 {
            state.fail_closes -= 1;
            return Err(ShellError::Backend("injected close failure".to_owned()));
        }
        Ok(())
    }
}

struct NoEffects;
impl PlatformAdapter for NoEffects {
    fn permission(&self, _: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        panic!("cleanup must not request platform permission")
    }
    fn invoke(
        &mut self,
        _: &OperationKey,
        _: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        panic!("cleanup must not dispatch an effect")
    }
    fn reconcile(&mut self, _: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        panic!("empty journal has no effect to reconcile")
    }
}

fn manifest() -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.1".to_owned(),
        address: "127.0.0.1:7373".to_owned(),
        manifest_digest: DIGEST.to_owned(),
        protocol_version: 1,
    }
}

fn session(id: &str) -> SessionIncarnation {
    SessionIncarnation {
        endpoint_id: "runtime.1".to_owned(),
        session_id: id.to_owned(),
        generation: 1,
    }
}

fn runtime(
    path: std::path::PathBuf,
    state: Arc<Mutex<BackendState>>,
    sessions: Vec<SessionIncarnation>,
) -> NativeShellRuntime {
    NativeShellRuntime::new(
        Box::new(Backend {
            state,
            sessions: sessions.into(),
        }),
        Box::new(NoEffects),
        None,
        OperationJournal::open(path).unwrap(),
    )
}

#[test]
fn failed_close_keeps_identity_without_usable_view_and_retries_same_owner() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(BackendState::default()));
    let original = session("session.close");
    let mut runtime = runtime(
        temp.path().join("operations.json"),
        Arc::clone(&state),
        vec![original.clone()],
    );
    runtime.connect_runtime(&manifest()).unwrap();
    runtime.refresh_runtime_view().unwrap();
    state.lock().unwrap().fail_closes = 1;
    assert!(runtime.close().is_err());
    assert_eq!(runtime.session(), Some(&original));
    assert!(runtime.view().is_none());
    assert!(runtime.refresh_runtime_view().is_err());
    runtime.close().unwrap();
    runtime.close().unwrap();
    assert!(runtime.session().is_none());
    assert_eq!(
        state.lock().unwrap().closes,
        vec![original.clone(), original]
    );
}

#[test]
fn reconnect_cannot_acquire_replacement_before_old_owner_is_closed() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(BackendState::default()));
    let first = session("session.first");
    let second = session("session.second");
    let mut runtime = runtime(
        temp.path().join("operations.json"),
        Arc::clone(&state),
        vec![first.clone(), second.clone()],
    );
    runtime.connect_runtime(&manifest()).unwrap();
    state.lock().unwrap().fail_closes = 1;
    assert!(runtime.connect_runtime(&manifest()).is_err());
    assert_eq!(state.lock().unwrap().connects, 1);
    assert_eq!(runtime.connect_runtime(&manifest()).unwrap(), second);
    let state = state.lock().unwrap();
    assert_eq!(state.connects, 2);
    assert_eq!(state.closes, vec![first.clone(), first]);
}

#[test]
fn rejected_session_cleanup_is_retained_but_never_exposed_as_active() {
    let temp = private_tempdir();
    let state = Arc::new(Mutex::new(BackendState {
        fail_closes: 2,
        ..BackendState::default()
    }));
    let mut rejected = session("session.rejected");
    rejected.endpoint_id = "runtime.wrong".to_owned();
    let mut runtime = runtime(
        temp.path().join("operations.json"),
        Arc::clone(&state),
        vec![rejected.clone()],
    );
    assert!(runtime.connect_runtime(&manifest()).is_err());
    assert!(runtime.session().is_none());
    assert!(runtime.refresh_runtime_view().is_err());
    assert!(runtime.connect_runtime(&manifest()).is_err());
    assert_eq!(state.lock().unwrap().connects, 1);
    runtime.close().unwrap();
    assert_eq!(
        state.lock().unwrap().closes,
        vec![rejected.clone(), rejected.clone(), rejected]
    );
}
