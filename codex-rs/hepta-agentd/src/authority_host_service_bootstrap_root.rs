//! Qualification consumes the public trusted-launcher product API.
use super::*;

pub(super) fn capture(
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
) -> crate::HostAuthorityPublicBootstrapV1 {
    let parent = config.state_dir.parent().unwrap();
    let config_path = parent.join("handoff-config.json");
    let registration_path = parent.join("handoff-registration.json");
    write_json(&config_path, config);
    write_json(&registration_path, registration);
    let local = config
        .sockets
        .observation
        .parent()
        .unwrap()
        .join("consumer-local");
    assert!(
        crate::capture_host_authority_bootstrap(
            &config_path,
            &registration_path,
            crate::HostAuthorityLocalConsumers {
                device: local.join("device"),
                notes: local.join("device")
            }
        )
        .is_err()
    );
    let absent = local.join("absent-consumer");
    assert!(
        crate::capture_host_authority_bootstrap(
            &config_path,
            &registration_path,
            crate::HostAuthorityLocalConsumers {
                device: local.join("device"),
                notes: absent.clone()
            }
        )
        .is_err()
    );
    assert!(
        !absent.exists(),
        "read-only capture must not initialize a missing consumer"
    );
    crate::capture_host_authority_bootstrap(
        &config_path,
        &registration_path,
        crate::HostAuthorityLocalConsumers {
            device: local.join("device"),
            notes: local.join("notes"),
        },
    )
    .unwrap()
}
