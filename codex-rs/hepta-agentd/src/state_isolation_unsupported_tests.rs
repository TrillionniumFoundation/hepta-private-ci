use super::*;

#[test]
fn unsupported_prompt_owner_prevents_daemon_admission_and_socket_publication() {
    let (_temp, registry, identity) = identity_fixture().expect("identity fixture");
    let before = registry.load().expect("registered starting agent");
    let control_socket = identity.control_socket.clone();
    let app_socket = identity.app_server_socket.clone();
    let registry_root = identity.home_root.join("prompt-registry");
    let runtime_root = identity.run_root.join("prompt-runtime");
    let result = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16);
    assert!(matches!(
        result,
        Err(AgentdError::Protocol(message))
            if message == r#"prompt pipeline durable owners failed to open: RegistryOpen("UnsafeStateDirectory")"#
    ));
    assert_eq!(registry.load().expect("unchanged registry"), before);
    assert!(!control_socket.exists());
    assert!(!app_socket.exists());
    assert!(!registry_root.exists());
    assert!(!runtime_root.exists());
}
