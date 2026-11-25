//! Trusted launcher for one unused original Notes model thread.
//!
//! This connects only through the already running Agentd session ingress,
//! creates no human turn, performs no model request, grants no authority and
//! executes no Notes effect. The output is metadata for the Root launch
//! profile; the final runtime must independently resume and verify it.

#[cfg(target_os = "linux")]
#[path = "notes_thread_seed/linux.rs"]
mod linux;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    return linux::run();

    #[cfg(not(target_os = "linux"))]
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Original Notes thread seeding requires Linux",
    )
    .into())
}
