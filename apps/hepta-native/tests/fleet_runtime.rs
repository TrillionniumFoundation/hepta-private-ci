mod common;

use std::collections::VecDeque;

use hepta_native::NativeShellRuntime;
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

const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const NEXT_EPOCH: &str = "028f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const DIGEST: &str = "1111111111111111111111111111111111111111111111111111111111111111";

fn observation(revision: u64, epoch: &str, pid: u32) -> serde_json::Value {
    serde_json::json!({
        "schema": "hepta_fleet_observation_v1", "observation_revision": revision,
        "health": {"ready": false, "supervisor_epoch": epoch,
            "process_id": pid, "registered_agents": 1, "observed_faults": 2},
        "agents": [{"agent_id": AGENT, "lifecycle": "failed", "lifecycle_generation": 9,
            "active": false, "healthy": false, "process_id": null, "current_release": "original-owner",
            "control_fence": {"supervisor_epoch": epoch},
            "matrix": {"configured": false, "healthy": false, "degraded": false, "last_error": null}}],
    })
}

struct Backend(VecDeque<serde_json::Value>);

impl BackendAdapter for Backend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        Ok(SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: "session.fleet".into(),
            generation: 1,
        })
    }

    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        let value = self.0.pop_front().expect("fixture observation");
        Ok(AuthenticatedRuntimeStatus {
            body_digest: hepta_native::model::sha256_hex(serde_json::to_vec(&value).unwrap()),
            value,
        })
    }

    fn close(&mut self, _session: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
}

struct NoEffects;

impl PlatformAdapter for NoEffects {
    fn permission(&self, _payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        panic!("read-only refresh must never request platform permission")
    }
    fn invoke(
        &mut self,
        _key: &OperationKey,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        panic!("read-only refresh must never perform a platform effect")
    }
    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        panic!("read-only refresh must never reconcile an operation")
    }
}

fn runtime(values: Vec<serde_json::Value>) -> (tempfile::TempDir, NativeShellRuntime) {
    let temp = common::private_tempdir();
    let journal = OperationJournal::open(temp.path().join("journal.json")).unwrap();
    let mut runtime = NativeShellRuntime::new(
        Box::new(Backend(values.into())),
        Box::new(NoEffects),
        /*final_use*/ None,
        journal,
    );
    runtime
        .connect_runtime(&EndpointManifest {
            endpoint_id: "runtime.fleet".into(),
            address: "127.0.0.1:7373".into(),
            manifest_digest: DIGEST.into(),
            protocol_version: 2,
        })
        .unwrap();
    (temp, runtime)
}

#[test]
fn failed_fleet_agents_and_owner_restart_render_without_a_legacy_database_snapshot() {
    let (_temp, mut runtime) = runtime(vec![
        observation(/*revision*/ 1, EPOCH, /*pid*/ 2233),
        observation(/*revision*/ 2, NEXT_EPOCH, /*pid*/ 2456),
    ]);
    let (first, value) = runtime.refresh_runtime_view().unwrap();
    assert_eq!(value["agents"][0]["lifecycle"], "failed");
    assert!(value.get("state").is_none());
    assert_eq!(
        first.modules,
        vec![format!("agent.{AGENT}"), "ui.native".into()]
    );
    let (next, value) = runtime.refresh_runtime_view().unwrap();
    assert_eq!((next.generation, next.revision), (2, 2));
    assert_ne!(first.digest, next.digest);
    assert_eq!(value["health"]["supervisor_epoch"], NEXT_EPOCH);
}

#[test]
fn stale_foreign_or_substituted_source_clears_the_previous_actionable_view() {
    let mut foreign = observation(/*revision*/ 2, EPOCH, /*pid*/ 2233);
    foreign["agents"][0]["control_fence"]["supervisor_epoch"] = NEXT_EPOCH.into();
    for invalid in [
        observation(/*revision*/ 1, EPOCH, /*pid*/ 2233),
        observation(/*revision*/ 2, EPOCH, /*pid*/ 9999),
        foreign,
        serde_json::json!({"state": {"runtime_snapshot_generation": 2}}),
    ] {
        let (_temp, mut runtime) = runtime(vec![
            observation(/*revision*/ 1, EPOCH, /*pid*/ 2233),
            invalid,
        ]);
        runtime.refresh_runtime_view().unwrap();
        assert!(runtime.refresh_runtime_view().is_err());
        assert!(runtime.view().is_none());
    }
}
