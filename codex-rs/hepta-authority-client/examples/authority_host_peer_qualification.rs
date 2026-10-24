//! Complete original five-lane peer and compatibility scenarios.
//! This entry uses the same qualification algorithm as the legacy Agentd example.

#[path = "shared/authority_host_peer_qualification.rs"]
mod shared;

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    shared::run()
}

#[cfg(not(target_os = "linux"))]
fn main() {
    shared::run()
}
