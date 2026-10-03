mod common;
use hepta_native::NativeShellRuntime;
use hepta_native::backend::AuthenticatedRuntimeStatus;
use hepta_native::backend::BackendAdapter;
use hepta_native::error::ShellError;
use hepta_native::fleet_lifecycle::FleetLifecycleOperation;
use hepta_native::journal::OperationJournal;
use hepta_native::journal::OperationRecord;
use hepta_native::model::EndpointManifest;
use hepta_native::model::OperationKey;
use hepta_native::model::PlatformObservation;
use hepta_native::model::PlatformPayload;
use hepta_native::model::SessionIncarnation;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::private_state::PrivateStateRoot;
use serde_json::Value;
use std::sync::Arc;
use std::sync::Mutex;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
struct State {
    revision: u64,
    calls: Vec<Value>,
    pending_path: std::path::PathBuf,
    terminal: bool,
    reject: bool,
}
struct Backend(Arc<Mutex<State>>);
fn authenticated(value: Value) -> AuthenticatedRuntimeStatus {
    AuthenticatedRuntimeStatus {
        body_digest: hepta_native::model::sha256_hex(serde_json::to_vec(&value).unwrap()),
        value,
    }
}
impl BackendAdapter for Backend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        Ok(SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: "session.fleet".into(),
            generation: 1,
        })
    }
    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        let mut state = self.0.lock().unwrap();
        state.revision += 1;
        let fence = serde_json::json!({"agent_id":AGENT,"supervisor_epoch":EPOCH,"lifecycle":"stopped",
            "lifecycle_generation":7,"spawn_generation":null,"runtime_generation":null,"current_release":"agentd-v1",
            "previous_release":null,"release_change_pending":false,"state_digest":"a".repeat(64)});
        Ok(authenticated(
            serde_json::json!({"schema":"hepta_fleet_observation_v1","observation_revision":state.revision,
            "health":{"ready":true,"supervisor_epoch":EPOCH,"process_id":2233,"registered_agents":1,"observed_faults":0},
            "agents":[{"agent_id":AGENT,"lifecycle":"stopped","lifecycle_generation":7,"active":false,"healthy":false,
                "process_id":null,"current_release":"agentd-v1","control_fence":fence,
                "matrix":{"configured":false,"healthy":false,"degraded":false,"last_error":null}}]}),
        ))
    }
    fn close(&mut self, _: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
    fn fleet_lifecycle_available(&self) -> bool {
        true
    }
    fn fleet_lifecycle(
        &mut self,
        operation: FleetLifecycleOperation,
        body: &Value,
    ) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        let mut state = self.0.lock().unwrap();
        let stored: Value =
            serde_json::from_slice(&std::fs::read(&state.pending_path).unwrap()).unwrap();
        if operation != FleetLifecycleOperation::Receipt {
            assert_eq!(stored["pending"]["request_id"], body["request_id"]);
            assert_eq!(
                stored["pending"]["accepted_state_digest"],
                body["method"]["fence"]["state_digest"]
            );
        } else {
            assert_eq!(
                stored["pending"]["request_id"],
                body["method"]["mutation_request_id"]
            );
        }
        state.calls.push(body.clone());
        if operation == FleetLifecycleOperation::Receipt {
            return Ok(authenticated(if state.terminal {
                serde_json::json!({"type":"ordinary_mutation_status","status":{"request_id":stored["pending"]["request_id"],
                    "agent_id":AGENT,"supervisor_epoch":EPOCH,"accepted_state_digest":"a".repeat(64),"operation":"start","phase":"committed"}})
            } else {
                serde_json::json!({"type":"ordinary_mutation_status","status":null})
            }));
        }
        if state.reject {
            return Ok(authenticated(
                serde_json::json!({"type":"error","code":"stale_control_fence","message":"refresh original owner"}),
            ));
        }
        Err(ShellError::Backend(
            "lost acknowledgement after request delivery".into(),
        ))
    }
}
struct NoEffects;
impl PlatformAdapter for NoEffects {
    fn permission(&self, _: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        panic!("Agent action cannot consume a platform grant")
    }
    fn invoke(
        &mut self,
        _: &OperationKey,
        _: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        panic!("Agent action cannot perform a desktop effect")
    }
    fn reconcile(&mut self, _: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        panic!("Agent receipts belong to Supervisor")
    }
}
fn runtime(root: &std::path::Path, state: Arc<Mutex<State>>) -> NativeShellRuntime {
    let mut runtime = NativeShellRuntime::new(
        Box::new(Backend(state)),
        Box::new(NoEffects),
        None,
        OperationJournal::open(root.join("journal.json")).unwrap(),
    )
    .enable_fleet_lifecycle(PrivateStateRoot::open(root).unwrap())
    .unwrap();
    runtime
        .connect_runtime(&EndpointManifest {
            endpoint_id: "runtime.fleet".into(),
            address: "127.0.0.1:7373".into(),
            manifest_digest: "1".repeat(64),
            protocol_version: 2,
        })
        .unwrap();
    runtime
}
#[test]
fn lost_acknowledgement_reopens_original_reference_and_never_retries_effect() {
    let temp = common::private_tempdir();
    let state = Arc::new(Mutex::new(State {
        revision: 0,
        calls: Vec::new(),
        pending_path: temp.path().join("fleet-lifecycle-pending.json"),
        terminal: false,
        reject: false,
    }));
    let mut shell = runtime(temp.path(), state.clone());
    let (view, _) = shell.refresh_runtime_view().unwrap();
    assert!(
        shell
            .execute_fleet_lifecycle(AGENT, FleetLifecycleOperation::Start, view.revision + 1)
            .is_err()
    );
    assert!(state.lock().unwrap().calls.is_empty());
    assert!(
        shell
            .execute_fleet_lifecycle(AGENT, FleetLifecycleOperation::Start, view.revision)
            .is_err()
    );
    assert!(shell.fleet_lifecycle_pending());
    assert!(shell.view().is_none());
    shell.close().unwrap();
    drop(shell);
    let mut recovered = runtime(temp.path(), state.clone());
    assert!(recovered.fleet_lifecycle_pending());
    let (view, _) = recovered.refresh_runtime_view().unwrap();
    assert!(
        recovered
            .execute_fleet_lifecycle(AGENT, FleetLifecycleOperation::Start, view.revision)
            .is_err()
    );
    assert!(!recovered.inspect_fleet_lifecycle_receipt().unwrap());
    assert!(recovered.fleet_lifecycle_pending());
    state.lock().unwrap().terminal = true;
    assert!(recovered.inspect_fleet_lifecycle_receipt().unwrap());
    assert!(!recovered.fleet_lifecycle_pending());
    let calls = &state.lock().unwrap().calls;
    assert_eq!(calls.len(), 3);
    assert_eq!(
        calls[0]["request_id"],
        calls[1]["method"]["mutation_request_id"]
    );
    assert_eq!(
        calls[0]["request_id"],
        calls[2]["method"]["mutation_request_id"]
    );
    assert_eq!(calls[0]["method"]["type"], "start");
}
#[test]
fn definitive_stale_owner_rejection_requires_new_verified_view() {
    let temp = common::private_tempdir();
    let state = Arc::new(Mutex::new(State {
        revision: 0,
        calls: Vec::new(),
        pending_path: temp.path().join("fleet-lifecycle-pending.json"),
        terminal: false,
        reject: true,
    }));
    let mut shell = runtime(temp.path(), state.clone());
    let (view, _) = shell.refresh_runtime_view().unwrap();
    assert!(
        shell
            .execute_fleet_lifecycle(AGENT, FleetLifecycleOperation::Start, view.revision)
            .is_err()
    );
    assert!(!shell.fleet_lifecycle_pending());
    assert!(shell.view().is_none());
    assert!(
        shell
            .execute_fleet_lifecycle(AGENT, FleetLifecycleOperation::Start, view.revision)
            .is_err()
    );
    assert_eq!(state.lock().unwrap().calls.len(), 1);
}
