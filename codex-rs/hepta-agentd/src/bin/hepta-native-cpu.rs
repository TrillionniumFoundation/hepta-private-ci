//! Final frozen G2 image. It dispatches only the actual kernel bootstrap role.
#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    codex_hepta_agentd::run_native_cpu_daemon()?;
    Ok(())
}
#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("native CPU roles require the reviewed Asterinas kernel");
    std::process::exit(1);
}
