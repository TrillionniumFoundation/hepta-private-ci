use super::*;

fn fixture() -> Result<(
    FleetResourceObservationRequestV1,
    FleetResourceObservationResponseV1,
)> {
    let response = serde_json::from_value(serde_json::json!({
        "schema_version":1,"operation":"fleet.resource.observe","observed_at_ms":100,
        "observation":{"context":{"execution_id":"execution","allocation_id":"execution","principal_id":"agent",
            "host_id":"host","host_generation":2,"lease_generation":1,"manifest_digest":"manifest",
            "resources":{"cpu_millis":1000,"memory_bytes":134217728,"accelerator_millis":0,
                "concurrent_turns":2,"tool_processes":1,"turn_queue_slots":64},"containment":"hepta/agent-agent/main-execution"},
            "process_id":11,"process_start_ticks":12,
            "allocation":{"allocation_id":"execution","request_id":"spawn:execution","principal_id":"agent",
                "host_id":"host","failure_domain_id":"local","host_generation":2,"authority_epoch":7,
                "lease_generation":205,"expires_at_ms":200,"semantic_digest":"manifest","revoked":false,
                "resources":{"cpu_millis":1000,"memory_bytes":134217728,"accelerator_millis":0,
                    "concurrent_turns":2,"tool_processes":1,"turn_queue_slots":64}}}
    }))?;
    let request = FleetResourceObservationRequestV1 {
        schema_version: 1,
        operation: FLEET_RESOURCE_OBSERVATION_OPERATION.into(),
        subject_id: "agent".into(),
        execution_id: "execution".into(),
        manifest_digest: "manifest".into(),
    };
    Ok((request, response))
}

#[test]
fn original_renewed_lease_is_preserved_and_late_expiry_rejected() -> Result<()> {
    let (request, response) = fixture()?;
    assert_eq!(
        validate_response(&request, &response, Duration::from_millis(20))?,
        response
            .observation
            .allocation
            .as_ref()
            .ok_or("allocation")?
    );
    assert!(validate_response(&request, &response, Duration::from_millis(100)).is_err());
    assert!(validate_response(&request, &response, TIMEOUT).is_err());
    Ok(())
}

#[test]
fn original_resource_response_rejects_absence_revocation_and_substitution() -> Result<()> {
    let (request, response) = fixture()?;
    let mut absent = response.clone();
    absent.observation.allocation = None;
    assert!(validate_response(&request, &absent, Duration::ZERO).is_err());
    for mutate in [
        |grant: &mut AllocationGrant| grant.revoked = true,
        |grant: &mut AllocationGrant| grant.lease_generation = 0,
        |grant: &mut AllocationGrant| grant.semantic_digest = "other".into(),
        |grant: &mut AllocationGrant| grant.principal_id = "other".into(),
        |grant: &mut AllocationGrant| grant.host_generation += 1,
        |grant: &mut AllocationGrant| grant.resources.memory_bytes += 1,
    ] {
        let mut changed = response.clone();
        mutate(
            changed
                .observation
                .allocation
                .as_mut()
                .ok_or("allocation")?,
        );
        assert!(validate_response(&request, &changed, Duration::ZERO).is_err());
    }
    Ok(())
}
