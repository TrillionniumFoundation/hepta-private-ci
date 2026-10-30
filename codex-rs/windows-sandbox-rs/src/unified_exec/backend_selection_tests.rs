#![cfg(target_os = "windows")]

use crate::backend_selection::WindowsSandboxBrokerRequest;
use crate::backend_selection::require_windows_sandbox_broker;
use codex_protocol::config_types::WindowsSandboxLevel;
use pretty_assertions::assert_eq;

#[test]
fn explicit_elevated_level_accepts_managed_network_configuration() {
    require_windows_sandbox_broker(&WindowsSandboxBrokerRequest {
        windows_sandbox_level: WindowsSandboxLevel::Elevated,
        proxy_enforced: true,
        network_proxy_restricting_sid: Some("S-1-5-21-50-60-70-80"),
    })
    .unwrap_or_else(|error| panic!("explicit elevated configuration must admit the broker: {error}"));
}

#[test]
fn managed_networking_still_requires_explicit_elevated_configuration() {
    for (proxy_enforced, network_proxy_restricting_sid, expected) in [
        (
            true,
            None,
            "managed networking requires the elevated Windows sandbox backend",
        ),
        (
            false,
            Some("S-1-5-21-50-60-70-80"),
            "network proxy restricting SID requires the elevated Windows sandbox backend",
        ),
    ] {
        let result = require_windows_sandbox_broker(&WindowsSandboxBrokerRequest {
            windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
            proxy_enforced,
            network_proxy_restricting_sid,
        });
        let Err(error) = result else {
            panic!("managed network configuration must require explicit elevated admission");
        };
        assert_eq!(error.to_string(), expected);
    }
}
