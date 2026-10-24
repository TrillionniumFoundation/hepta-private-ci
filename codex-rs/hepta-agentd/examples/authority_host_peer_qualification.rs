//! Legacy package entry retains every original qualification mode.
//! The finite package entry compiles this same complete implementation.

#[path = "../../hepta-authority-client/examples/shared/authority_host_peer_qualification.rs"]
mod shared;

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    shared::run()
}

#[cfg(not(target_os = "linux"))]
fn main() {
    shared::run()
}
