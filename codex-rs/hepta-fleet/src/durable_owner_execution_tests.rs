// Included in durable_owner_tests.rs to reuse the real authority fixture.
#[cfg(unix)]
struct ChildQuiescenceProbe(std::sync::Mutex<std::process::Child>);

#[cfg(unix)]
impl crate::FleetQuiescenceProbe for ChildQuiescenceProbe {
    fn is_quiescent(&self, _hold: &crate::FleetExecutionHoldV1) -> std::io::Result<bool> {
        let mut child = self
            .0
            .lock()
            .map_err(|_| std::io::Error::other("child lock poisoned"))?;
        Ok(child.try_wait()?.is_some())
    }
}

#[cfg(unix)]
impl Drop for ChildQuiescenceProbe {
    fn drop(&mut self) {
        if let Ok(mut child) = self.0.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(unix)]
struct UnavailableQuiescenceProbe;

#[cfg(unix)]
impl crate::FleetQuiescenceProbe for UnavailableQuiescenceProbe {
    fn is_quiescent(&self, _hold: &crate::FleetExecutionHoldV1) -> std::io::Result<bool> {
        Err(std::io::Error::other(
            "selected-host observation unavailable",
        ))
    }
}

#[cfg(unix)]
fn physical_hold_case(revoke: bool) {
    let directory = tempfile::tempdir().expect("tempdir");
    let state_root = directory.path().join("state");
    std::fs::create_dir(&state_root).expect("state");
    let clock = Arc::new(ManualClock::new(2_000));
    let mut owner =
        DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone()).expect("owner");
    owner
        .resolve_host_incarnation("host-one", "rack-one", &"a".repeat(64), None)
        .expect("incarnation");
    owner
        .refresh_capacity("capacity", &FixedObserver)
        .expect("capacity");
    let first = grant(2_500);
    let authority = authority_port(&directory, "first-authority", clock.clone(), &first);
    owner
        .issue_with_authority("first", &authority, "fleet-issue-one", 1, first.clone())
        .expect("grant");
    let snapshot = FleetRevocationSnapshotV1::empty(1_000);
    let revocation_digest = snapshot.semantic_digest().expect("snapshot digest");
    owner
        .persist_revocation_snapshot("revocation-fixture", snapshot)
        .expect("snapshot");
    let witness = crate::RevocationBoundGrantUseWitnessV1 {
        grant: owner
            .verify_final_use(
                &first.allocation_id,
                1,
                "host-one",
                1,
                &first.semantic_digest,
            )
            .expect("use"),
        revocation_snapshot_sha256: revocation_digest,
        revocation_authority_epoch: 7,
        revocation_revision: 1,
        node_id: "fixture-node".into(),
    };
    let context = crate::FleetExecutionContextV1 {
        principal_id: first.principal_id.clone(),
        host_id: first.host_id.clone(),
        host_generation: 1,
        boot_identity: "a".repeat(64),
        resources: first.resources,
        execution_sha256: "b".repeat(64),
    };
    let mut excessive = context.clone();
    excessive.resources = ResourceVectorV1::physical(1_000, 1 << 20, 0);
    assert!(
        owner
            .prepare_execution("wrong-budget", excessive, &witness)
            .is_err()
    );
    let mut wrong_host = context.clone();
    wrong_host.host_id = "other-host".into();
    assert!(
        owner
            .prepare_execution("wrong-host", wrong_host, &witness)
            .is_err()
    );
    let mut wrong_boot = context.clone();
    wrong_boot.boot_identity = "c".repeat(64);
    assert!(
        owner
            .prepare_execution("wrong-boot", wrong_boot, &witness)
            .is_err()
    );
    owner
        .prepare_execution("actual-child", context.clone(), &witness)
        .expect("intent before spawn");
    let pinned_state_sha = owner.state().content_sha256.clone();
    assert!(matches!(
        owner.prepare_execution("renamed-effect", context.clone(), &witness),
        Err(DurableFleetError::ExecutionAlreadyPrepared)
    ));
    let mut second_context = context.clone();
    second_context.execution_sha256 = "d".repeat(64);
    assert!(matches!(
        owner.prepare_execution("same-grant-second-child", second_context, &witness),
        Err(DurableFleetError::Ledger(
            crate::LeaseLedgerError::CapacityExceeded
        ))
    ));
    assert_eq!(owner.state().content_sha256, pinned_state_sha);
    assert_eq!(owner.state().fleet_execution_holds.len(), 1);
    assert!(
        owner
            .prepare_execution("actual-child", context, &witness)
            .is_err(),
        "duplicate effect must not fork again"
    );
    let child = std::process::Command::new("/bin/sleep")
        .arg("60")
        .spawn()
        .expect("real child");
    let probe = ChildQuiescenceProbe(std::sync::Mutex::new(child));
    if revoke {
        owner
            .renew_or_revoke(
                "revoke",
                &first.allocation_id,
                1,
                7,
                &first.semantic_digest,
                LeaseDisposition::Revoke,
            )
            .expect("revoke");
    } else {
        clock.set(2_500);
        owner.reconcile_expired("expire").expect("expiry");
    }
    drop(owner);
    // A real owner reopen must retain the physical pin after authorization ends.
    let mut owner = DurableFleetOwner::open_supervisor_state_root(&state_root, clock.clone())
        .expect("recover owner");
    assert_eq!(owner.metrics().expect("metrics").fleet_active_grants, 0);
    assert_eq!(
        owner.metrics().expect("metrics").fleet_reserved_resource["host-one"],
        first.resources
    );
    let before_probe = owner.state().content_sha256.clone();
    assert!(
        owner
            .reconcile_execution_group(&first.allocation_id, &UnavailableQuiescenceProbe)
            .is_err()
    );
    assert_eq!(owner.state().content_sha256, before_probe);
    assert_eq!(owner.state().fleet_execution_holds.len(), 1);
    assert!(
        !owner
            .reconcile_execution_group(&first.allocation_id, &probe)
            .expect("still running")
    );
    let mut second = grant(7_000);
    second.allocation_id = "allocation-two".into();
    second.request_id = "request-two".into();
    second.principal_id = "agent-two".into();
    second.resources = ResourceVectorV1::physical(1_000, 1 << 20, 0);
    let authority = authority_port(&directory, "second-authority", clock.clone(), &second);
    assert!(matches!(
        owner.issue_with_authority("second", &authority, "fleet-issue-one", 1, second.clone()),
        Err(DurableFleetError::Ledger(
            crate::LeaseLedgerError::CapacityExceeded
        ))
    ));
    {
        let mut child = probe.0.lock().expect("child");
        child.kill().expect("stop request");
        // Never call the accounting release merely because kill returned Ok.
        child.wait().expect("observed exit");
    }
    assert!(
        owner
            .reconcile_execution_group(&first.allocation_id, &probe)
            .expect("confirmed stopped")
    );
    assert!(owner.state().fleet_resource_totals.is_empty());
    owner
        .issue_with_authority("second", &authority, "fleet-issue-one", 1, second)
        .expect("readmission after physical exit");
}

#[cfg(unix)]
#[test]
fn expiry_reopen_and_real_child_exit_gate_capacity_readmission() {
    physical_hold_case(false);
}

#[cfg(unix)]
#[test]
fn revocation_does_not_release_a_still_running_real_child() {
    physical_hold_case(true);
}
