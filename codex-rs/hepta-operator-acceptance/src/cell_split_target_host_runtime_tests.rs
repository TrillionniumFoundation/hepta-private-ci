use super::*;
use crate::CellSplitTargetHardwareV1;
use crate::CellSplitTargetHostEventKindV1;
use std::fmt;
use std::fs;
use std::path::Path;
use tempfile::tempdir;

const PARENT: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const CHILD: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const ATTESTATION: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const TOMBSTONE: &str = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";

#[cfg(unix)]
fn make_private(paths: &[&Path]) {
    use std::os::unix::fs::PermissionsExt;
    for path in paths {
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).expect("private file");
    }
}

#[derive(Debug)]
struct FakeError(&'static str);
impl fmt::Display for FakeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

struct FakeRuntime {
    next_timestamp: u128,
    calls: Vec<&'static str>,
}
impl FakeRuntime {
    fn new() -> Self {
        Self {
            next_timestamp: 1_700_000_000_000_000_000,
            calls: Vec::new(),
        }
    }
    fn operation(&mut self, name: &'static str) -> CellSplitTargetHostOperationReceiptV1 {
        self.calls.push(name);
        self.next_timestamp += 1;
        let n = self.calls.len();
        CellSplitTargetHostOperationReceiptV1 {
            operation_id: format!("operation-{n}"),
            occurred_at_unix_nanos: self.next_timestamp,
            artifact_digest: (name == "load")
                .then(|| CHILD.to_string())
                .unwrap_or_default(),
            route_digest: (name == "route")
                .then(|| "route-child".to_string())
                .unwrap_or_default(),
            predecessor_digest: matches!(name, "route" | "rollback" | "resurrection")
                .then(|| "route-parent-fence".to_string())
                .unwrap_or_default(),
            tombstone_digest: matches!(name, "tombstone" | "resurrection")
                .then(|| TOMBSTONE.to_string())
                .unwrap_or_default(),
            fault_injection_digest: (name == "power-loss")
                .then(|| ATTESTATION.to_string())
                .unwrap_or_default(),
            receipt_digest: format!("receipt-{n}"),
        }
    }
}
impl CellSplitTargetHostRuntimeV1 for FakeRuntime {
    type Error = FakeError;
    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("load"))
    }
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("route"))
    }
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("restart"))
    }
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("power-loss"))
    }
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("rollback"))
    }
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("tombstone"))
    }
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Ok(self.operation("resurrection"))
    }
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        Ok(vec![CellSplitTargetHostMeasurementV1 {
            operation: self.operation("resource"),
            sample: crate::CellSplitTargetResourceSampleV1 {
                hardware: CellSplitTargetHardwareV1::Cpu,
                hardware_model: "externally-reported-cpu".to_string(),
                measurement_source: "external-counter".to_string(),
                hardware_attestation_digest: ATTESTATION.to_string(),
                sample_count: 1,
                latency_micros: 1,
                memory_bytes: 1,
                communication_bytes: 1,
                training_micros: 1,
                migration_micros: 1,
            },
        }])
    }
}

fn recorder() -> CellSplitTargetHostEvidenceRecorderV1 {
    CellSplitTargetHostEvidenceRecorderV1::new(
        "split.runner.1",
        "host.external.1",
        "nonce.runner.1",
        ATTESTATION,
        7,
        8,
        PARENT,
        CHILD,
    )
    .expect("recorder")
}

#[test]
fn runner_orders_external_lifecycle_and_returns_unsigned_payload() {
    let payload = CellSplitTargetHostLifecycleRunnerV1::new(FakeRuntime::new(), recorder())
        .run()
        .expect("lifecycle");
    assert_eq!(payload.origin, "production-target-host");
    assert_eq!(payload.events.len(), 8);
    assert_eq!(
        payload
            .events
            .iter()
            .map(|event| event.event_kind)
            .collect::<Vec<_>>(),
        vec![
            CellSplitTargetHostEventKindV1::ArtifactLoaded,
            CellSplitTargetHostEventKindV1::ResourceMeasurement,
            CellSplitTargetHostEventKindV1::RouteCutover,
            CellSplitTargetHostEventKindV1::RestartRecovered,
            CellSplitTargetHostEventKindV1::PowerLossRecovered,
            CellSplitTargetHostEventKindV1::RollbackCompleted,
            CellSplitTargetHostEventKindV1::TombstoneCommitted,
            CellSplitTargetHostEventKindV1::NoResurrectionVerified,
        ]
    );
    assert_eq!(payload.events[0].artifact_digest, CHILD);
    assert_eq!(payload.events[4].fault_injection_digest, ATTESTATION);
    assert_eq!(payload.events[6].tombstone_digest, TOMBSTONE);
    assert_eq!(payload.evidence_digest.len(), 64);
}

#[test]
fn local_file_runtime_runs_lifecycle_but_requires_external_power_witness() {
    let directory = tempfile::tempdir().expect("directory");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))
            .expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.current");
    let tombstone = root.join("tombstone");
    let power_loss = root.join("power-loss.witness");
    std::fs::write(&parent_artifact, b"parent-artifact").expect("parent artifact");
    std::fs::write(&child_artifact, b"child-artifact").expect("child artifact");
    std::fs::write(&state, b"parent-state").expect("parent state");
    std::fs::write(&route, b"parent-route").expect("parent route");
    std::fs::write(&power_loss, b"external-fault-injection-witness").expect("power loss");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for path in [
            &parent_artifact,
            &child_artifact,
            &state,
            &route,
            &power_loss,
        ] {
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
                .expect("private file");
        }
    }
    let parent_digest = {
        use sha2::Digest as _;
        use sha2::Sha256;
        format!("{:x}", Sha256::digest(b"parent-artifact"))
    };
    let child_digest = {
        use sha2::Digest as _;
        use sha2::Sha256;
        format!("{:x}", Sha256::digest(b"child-artifact"))
    };
    let recorder = CellSplitTargetHostEvidenceRecorderV1::new(
        "split.local-runtime.1",
        "host.local-runtime.1",
        "nonce.local-runtime.1",
        ATTESTATION,
        7,
        8,
        parent_digest,
        child_digest,
    )
    .expect("recorder");
    let runtime = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        crate::CellSplitTargetResourceSampleV1 {
            hardware: CellSplitTargetHardwareV1::Cpu,
            hardware_model: "externally-reported-cpu".to_string(),
            measurement_source: "external-counter".to_string(),
            hardware_attestation_digest: ATTESTATION.to_string(),
            sample_count: 1,
            latency_micros: 10,
            memory_bytes: 4096,
            communication_bytes: 100,
            training_micros: 20,
            migration_micros: 30,
        },
        7,
    )
    .expect("local runtime");
    let payload = CellSplitTargetHostLifecycleRunnerV1::new(runtime, recorder)
        .run()
        .expect("local lifecycle");
    assert_eq!(payload.events.len(), 8);
    assert_eq!(
        payload.events[3].event_kind,
        CellSplitTargetHostEventKindV1::RestartRecovered
    );
    assert_eq!(
        payload.events[4].event_kind,
        CellSplitTargetHostEventKindV1::PowerLossRecovered
    );
    assert_eq!(
        payload.events[6].event_kind,
        CellSplitTargetHostEventKindV1::TombstoneCommitted
    );
}

struct EmptyRuntime;
impl CellSplitTargetHostRuntimeV1 for EmptyRuntime {
    type Error = FakeError;
    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        Err(FakeError("no deployment owner"))
    }
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        unreachable!()
    }
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        unreachable!()
    }
}

#[test]
fn missing_external_owner_fails_before_any_production_payload_is_finished() {
    let error = CellSplitTargetHostLifecycleRunnerV1::new(EmptyRuntime, recorder())
        .run()
        .expect_err("deployment owner is required");
    assert!(error.to_string().contains("no deployment owner"));
}

#[test]
fn local_runtime_performs_real_file_lifecycle_and_requires_external_power_witness() {
    let directory = tempdir().expect("tempdir");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.snapshot");
    let tombstone = root.join("tombstone.snapshot");
    let power_loss = root.join("power-loss.witness");
    fs::write(&parent_artifact, b"parent-artifact-v1").expect("parent");
    fs::write(&child_artifact, b"child-artifact-v2").expect("child");
    fs::write(&state, b"parent-state-v1").expect("state");
    fs::write(&route, b"generation=7\nartifact=parent\n").expect("route");
    fs::write(&power_loss, b"externally-injected-power-loss-witness").expect("power witness");
    #[cfg(unix)]
    make_private(&[
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &power_loss,
    ]);
    let parent_digest = digest_bytes(&fs::read(&parent_artifact).expect("parent bytes"));
    let child_digest = digest_bytes(&fs::read(&child_artifact).expect("child bytes"));
    let resource = CellSplitTargetResourceSampleV1 {
        hardware: CellSplitTargetHardwareV1::Cpu,
        hardware_model: "host-cpu".to_string(),
        measurement_source: "external-counter".to_string(),
        hardware_attestation_digest: ATTESTATION.to_string(),
        sample_count: 1,
        latency_micros: 11,
        memory_bytes: 4096,
        communication_bytes: 12,
        training_micros: 3,
        migration_micros: 4,
    };
    let runtime = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        parent_artifact,
        child_artifact,
        state,
        route,
        tombstone,
        power_loss,
        resource.clone(),
        7,
    )
    .expect("local runtime");
    let recorder = CellSplitTargetHostEvidenceRecorderV1::new(
        "split.local.1",
        "host.local.1",
        "nonce.local.1",
        ATTESTATION,
        7,
        8,
        parent_digest,
        child_digest,
    )
    .expect("recorder");
    let payload = CellSplitTargetHostLifecycleRunnerV1::new(runtime, recorder)
        .run()
        .expect("local lifecycle");
    assert_eq!(payload.events.len(), 8);
    assert_eq!(
        payload.events.last().expect("no resurrection").event_kind,
        CellSplitTargetHostEventKindV1::NoResurrectionVerified
    );
}

#[test]
fn local_runtime_refuses_to_label_restart_as_power_loss() {
    let directory = tempdir().expect("tempdir");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.snapshot");
    let tombstone = root.join("tombstone.snapshot");
    let power_loss = root.join("missing-power-loss.witness");
    fs::write(&parent_artifact, b"parent").expect("parent");
    fs::write(&child_artifact, b"child").expect("child");
    fs::write(&state, b"state").expect("state");
    fs::write(&route, b"parent-route").expect("route");
    #[cfg(unix)]
    make_private(&[&parent_artifact, &child_artifact, &state, &route]);
    let mut runtime = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        parent_artifact,
        child_artifact,
        state,
        route,
        tombstone,
        power_loss,
        CellSplitTargetResourceSampleV1 {
            hardware: CellSplitTargetHardwareV1::Cpu,
            hardware_model: "host-cpu".to_string(),
            measurement_source: "external-counter".to_string(),
            hardware_attestation_digest: ATTESTATION.to_string(),
            sample_count: 1,
            latency_micros: 1,
            memory_bytes: 1,
            communication_bytes: 1,
            training_micros: 1,
            migration_micros: 1,
        },
        7,
    )
    .expect("local runtime");
    runtime.load_child_artifact().expect("load");
    runtime.route_cutover().expect("cutover");
    runtime.restart_recover().expect("restart");
    let error = runtime
        .power_loss_recover()
        .expect_err("missing external witness");
    assert!(error.to_string().contains("external power-loss witness"));
}

#[test]
fn local_runtime_reopens_after_process_restart_and_rolls_back_from_persisted_parent() {
    let directory = tempdir().expect("tempdir");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.snapshot");
    let tombstone = root.join("tombstone.snapshot");
    let power_loss = root.join("power-loss.witness");
    fs::write(&parent_artifact, b"parent").expect("parent");
    fs::write(&child_artifact, b"child").expect("child");
    fs::write(&state, b"state").expect("state");
    fs::write(&route, b"parent-route").expect("route");
    fs::write(&power_loss, b"external-power-loss").expect("power loss");
    #[cfg(unix)]
    make_private(&[
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &power_loss,
    ]);
    let resource = CellSplitTargetResourceSampleV1 {
        hardware: CellSplitTargetHardwareV1::Cpu,
        hardware_model: "host-cpu".to_string(),
        measurement_source: "external-counter".to_string(),
        hardware_attestation_digest: ATTESTATION.to_string(),
        sample_count: 1,
        latency_micros: 1,
        memory_bytes: 1,
        communication_bytes: 1,
        training_micros: 1,
        migration_micros: 1,
    };
    let mut first = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        resource.clone(),
        7,
    )
    .expect("first runtime");
    first.load_child_artifact().expect("load");
    first.route_cutover().expect("cutover");
    first.restart_recover().expect("same-process restart");
    drop(first);

    let mut reopened = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        resource.clone(),
        7,
    )
    .expect("reopened runtime");
    reopened
        .restart_recover()
        .expect("clean-process restart recovery");
    reopened.rollback().expect("rollback");
    reopened.commit_tombstone().expect("tombstone");
    reopened.verify_no_resurrection().expect("no resurrection");
    let error = reopened
        .load_child_artifact()
        .expect_err("a tombstoned generation must not be loadable again");
    assert!(error.to_string().contains("tombstoned"));
    drop(reopened);
    let mut reopened_after_tombstone = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        resource,
        7,
    )
    .expect("tombstone can be verified after process restart");
    reopened_after_tombstone
        .verify_no_resurrection()
        .expect("persisted tombstone blocks resurrection after restart");
}

#[test]
fn local_runtime_rejects_route_state_pair_tampering_on_reopen() {
    let directory = tempdir().expect("tempdir");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.snapshot");
    let tombstone = root.join("tombstone.snapshot");
    let power_loss = root.join("power-loss.witness");
    fs::write(&parent_artifact, b"parent").expect("parent");
    fs::write(&child_artifact, b"child").expect("child");
    fs::write(&state, b"state").expect("state");
    fs::write(&route, b"parent-route").expect("route");
    fs::write(&power_loss, b"external-power-loss").expect("power loss");
    #[cfg(unix)]
    make_private(&[
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &power_loss,
    ]);
    let resource = CellSplitTargetResourceSampleV1 {
        hardware: CellSplitTargetHardwareV1::Cpu,
        hardware_model: "host-cpu".to_string(),
        measurement_source: "external-counter".to_string(),
        hardware_attestation_digest: ATTESTATION.to_string(),
        sample_count: 1,
        latency_micros: 1,
        memory_bytes: 1,
        communication_bytes: 1,
        training_micros: 1,
        migration_micros: 1,
    };
    let mut runtime = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        resource.clone(),
        7,
    )
    .expect("runtime");
    runtime.load_child_artifact().expect("load");
    runtime.route_cutover().expect("cutover");
    drop(runtime);
    fs::write(&state, b"tampered-state").expect("tamper state");
    let error = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        parent_artifact,
        child_artifact,
        state,
        route,
        tombstone,
        power_loss,
        resource,
        7,
    )
    .expect_err("a publication fence must reject a mismatched route/state pair");
    assert!(error.to_string().contains("publication fence"));
}

#[test]
fn local_runtime_rejects_tampered_parent_snapshot_on_reopen() {
    let directory = tempdir().expect("tempdir");
    let root = directory.path();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700)).expect("private directory");
    }
    let parent_artifact = root.join("parent.artifact");
    let child_artifact = root.join("child.artifact");
    let state = root.join("state.snapshot");
    let route = root.join("route.snapshot");
    let tombstone = root.join("tombstone.snapshot");
    let power_loss = root.join("power-loss.witness");
    fs::write(&parent_artifact, b"parent").expect("parent");
    fs::write(&child_artifact, b"child").expect("child");
    fs::write(&state, b"state").expect("state");
    fs::write(&route, b"parent-route").expect("route");
    fs::write(&power_loss, b"external-power-loss").expect("power loss");
    #[cfg(unix)]
    make_private(&[
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &power_loss,
    ]);
    let resource = CellSplitTargetResourceSampleV1 {
        hardware: CellSplitTargetHardwareV1::Cpu,
        hardware_model: "host-cpu".to_string(),
        measurement_source: "external-counter".to_string(),
        hardware_attestation_digest: ATTESTATION.to_string(),
        sample_count: 1,
        latency_micros: 1,
        memory_bytes: 1,
        communication_bytes: 1,
        training_micros: 1,
        migration_micros: 1,
    };
    let mut runtime = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        &parent_artifact,
        &child_artifact,
        &state,
        &route,
        &tombstone,
        &power_loss,
        resource.clone(),
        7,
    )
    .expect("runtime");
    runtime.load_child_artifact().expect("load");
    runtime.route_cutover().expect("cutover");
    drop(runtime);

    let parent_route_snapshot = route.with_extension("local-target-host.parent-route");
    fs::write(&parent_route_snapshot, b"tampered-parent-route").expect("tamper snapshot");
    let error = LocalCellSplitTargetHostRuntimeV1::new(
        root,
        parent_artifact,
        child_artifact,
        state,
        route,
        tombstone,
        power_loss,
        resource,
        7,
    )
    .expect_err("tampered parent snapshot must fail closed");
    assert!(error.to_string().contains("predecessor"));
}
