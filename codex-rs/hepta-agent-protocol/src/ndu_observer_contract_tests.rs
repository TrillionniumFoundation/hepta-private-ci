//! Shared with the operational observer: schema changes must update both consumers.
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::NduControlRequestV1;
use crate::NduControlResultV1;

#[test]
fn observer_wire_fixture_round_trips_through_actual_protocol_types()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/ndu-observer-wire.json"))?;
    for (index, request) in [
        NduControlRequestV1::MetricsV2 {},
        NduControlRequestV1::MetricsV1,
    ]
    .into_iter()
    .enumerate()
    {
        let wire = AgentdRequest {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: u64::try_from(index)? + 1,
            spawn_generation: 7,
            method: AgentdMethod::NduControl { request },
        };
        assert_eq!(serde_json::to_value(wire)?, fixture["requests"][index]);
        let response: AgentdResponse = serde_json::from_value(fixture["responses"][index].clone())?;
        assert!(matches!(
            &response.payload,
            AgentdPayload::NduControl(NduControlResultV1::MetricsV1 { .. })
                | AgentdPayload::NduControl(NduControlResultV1::MetricsV2 { .. })
        ));
        assert_eq!(serde_json::to_value(response)?, fixture["responses"][index]);
    }
    Ok(())
}
