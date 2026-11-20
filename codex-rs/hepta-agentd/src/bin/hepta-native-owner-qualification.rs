//! Explicit sealed-image guest qualification of the original Root and Agentd.
//! The qualification path requires HOS2BOOT v2 and the actual process-bound
//! device. Original hidden helper re-execs dispatch before those role checks.
//! Fresh qualification Root state is not production.
#[path = "native_owner_qualification/agent.rs"]
#[cfg(target_os = "linux")]
mod agent;
#[path = "native_owner_qualification/common.rs"]
#[cfg(target_os = "linux")]
mod common;
#[path = "native_owner_qualification/history.rs"]
#[cfg(target_os = "linux")]
mod history;
#[path = "native_owner_qualification/root.rs"]
#[cfg(target_os = "linux")]
mod root;

#[cfg(target_os = "linux")]
fn main() {
    codex_arg0::dispatch_hidden_helper_if_requested();
    let result = common::Boot::read().and_then(|boot| match boot.role {
        1 => root::run(boot),
        2 => {
            if unsafe { libc::geteuid() } != 60001 {
                return Err(anyhow::anyhow!("workload UID differs"));
            }
            loop {
                std::hint::black_box(123_u64.wrapping_mul(456));
            }
        }
        3 => agent::run(boot),
        _ => Err(anyhow::anyhow!("unrecognized sealed role")),
    });
    if let Err(error) = result {
        eprintln!(
            "HEPTA_NATIVE_FAILURE pid={} error={error:#}",
            std::process::id()
        );
        std::process::exit(1);
    }
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("native owner qualification requires the sealed Linux ABI guest");
    std::process::exit(1);
}
