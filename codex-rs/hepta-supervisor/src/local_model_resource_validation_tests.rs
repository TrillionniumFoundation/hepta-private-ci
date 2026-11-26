use super::*;

fn fixture() -> anyhow::Result<(
    FleetResourceObservationRequestV1,
    Peer,
    FleetExecutionResourceObservationV1,
)> {
    let observation: FleetExecutionResourceObservationV1 = serde_json::from_value(
        serde_json::json!({
            "context":{"execution_id":"execution", "allocation_id":"execution","principal_id":"agent",
                "host_id":"host","host_generation":1,"lease_generation":1,"manifest_digest":"manifest",
                "resources":{"cpu_millis":1000,"memory_bytes":134217728,"accelerator_millis":0,
                    "concurrent_turns":1,"tool_processes":1,"turn_queue_slots":64},"containment":"hepta/agent-agent/main-execution"},
            "process_id":11,"process_start_ticks":12,
            "allocation":{"allocation_id":"execution","request_id":"spawn:execution","principal_id":"agent",
                "host_id":"host","failure_domain_id":"local","host_generation":1,"authority_epoch":7,
                "lease_generation":5,"expires_at_ms":200,"semantic_digest":"manifest","revoked":false,
                "resources":{"cpu_millis":1000,"memory_bytes":134217728,"accelerator_millis":0,
                    "concurrent_turns":1,"tool_processes":1,"turn_queue_slots":64}}
        }),
    )?;
    let request = FleetResourceObservationRequestV1 {
        schema_version: 1,
        operation: FLEET_RESOURCE_OBSERVATION_OPERATION.into(),
        subject_id: "agent".into(),
        execution_id: "execution".into(),
        manifest_digest: "manifest".into(),
    };
    let peer = Peer {
        pid: 11,
        start_ticks: 12,
        subject: "agent".into(),
        cgroup: "0::/hepta/agent-agent/main-execution".into(),
        cgroup_device: 1,
        cgroup_inode: 2,
        executable_device: 1,
        executable_inode: 3,
        executable_sha256: "a".repeat(64),
    };
    Ok((request, peer, observation))
}

#[test]
fn resource_currentness_rejects_missing_revoked_expired_and_wrong_epoch() -> anyhow::Result<()> {
    let (request, peer, observation) = fixture()?;
    validate_current(
        &request,
        &peer,
        &observation,
        /*authority_epoch*/ 7,
        /*now*/ 100,
    )?;
    assert!(
        validate_current(
            &request,
            &peer,
            &observation,
            /*authority_epoch*/ 7,
            /*now*/ 200
        )
        .is_err()
    );
    assert!(
        validate_current(
            &request,
            &peer,
            &observation,
            /*authority_epoch*/ 8,
            /*now*/ 100
        )
        .is_err()
    );
    let mut changed = observation;
    changed
        .allocation
        .as_mut()
        .context("missing fixture grant")?
        .revoked = true;
    assert!(
        validate_current(
            &request, &peer, &changed, /*authority_epoch*/ 7, /*now*/ 100
        )
        .is_err()
    );
    changed.allocation = None;
    assert!(
        validate_current(
            &request, &peer, &changed, /*authority_epoch*/ 7, /*now*/ 100
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn resource_binding_rejects_foreign_request_and_replacement_process() -> anyhow::Result<()> {
    let (request, peer, observation) = fixture()?;
    for field in [
        "schema_version",
        "operation",
        "subject_id",
        "execution_id",
        "manifest_digest",
    ] {
        let mut changed = serde_json::to_value(&request)?;
        changed[field] = if field == "schema_version" {
            2.into()
        } else {
            "foreign".into()
        };
        assert!(
            validate_current(
                &serde_json::from_value(changed)?,
                &peer,
                &observation,
                /*authority_epoch*/ 7,
                /*now*/ 100
            )
            .is_err()
        );
    }
    for replace_pid in [false, true] {
        let mut changed = observation.clone();
        if replace_pid {
            changed.process_id += 1;
        } else {
            changed.process_start_ticks += 1;
        }
        assert!(
            validate_current(
                &request, &peer, &changed, /*authority_epoch*/ 7, /*now*/ 100
            )
            .is_err()
        );
    }
    Ok(())
}
