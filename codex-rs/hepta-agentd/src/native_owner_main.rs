// Shared owner tests run in the original library. This explicit binary target
// has test=false; all-target clippy also requests a duplicate test-mode binary,
// whose Full-owner test fixtures cannot describe this native composition.
// Non-test binary checks and the original release/native execution still build
// every native owner below.
#![cfg(not(test))]

// Final G2 image composed from the same original shared owner sources.
// Full Agentd APIs remain in lib.rs; this root has no Full execution owner.

#[cfg(target_os = "linux")]
include!("native_owner_modules.rs");

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    run_native_cpu_daemon()?;
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("native CPU roles require the reviewed Asterinas kernel");
    std::process::exit(1);
}
