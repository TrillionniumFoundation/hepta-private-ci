use super::*;
fn observation() -> NativeObservation {
    NativeObservation {
        endpoint_id: "endpoint.1".into(),
        session_id: "session.1".into(),
        session_generation: 1,
        generation: 7,
        revision: 2,
        digest: "a".repeat(64),
        modules: vec!["ui.native".into(), "runtime.agentd".into()],
    }
}
#[test]
fn native_adapter_preserves_owner_identity_without_inventing_health_or_authority() {
    let projected = project_native_view(observation()).unwrap();
    let mut expected = observation();
    expected.modules.reverse();
    assert_eq!(
        projected,
        NativeReadOnlyProjection {
            observation: expected,
            read_only: true,
            mutation_available: false
        }
    );
}
#[test]
fn native_adapter_rejects_changed_or_unbounded_identity() {
    let mut value = observation();
    value.modules.push("ui.native".into());
    assert!(project_native_view(value).is_err());
    let mut value = observation();
    value.digest = "0".repeat(64);
    assert!(project_native_view(value).is_err());
    let mut value = observation();
    value.modules = vec!["ui.native".into(); 1001];
    assert!(project_native_view(value).is_err());
}
