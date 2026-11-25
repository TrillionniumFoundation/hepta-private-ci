#[cfg(target_os = "linux")]
#[path = "notes_thread_seed_product/linux.rs"]
mod linux;

#[cfg(not(target_os = "linux"))]
#[test]
fn launcher_reports_unsupported_on_non_linux() -> anyhow::Result<()> {
    let output =
        std::process::Command::new(codex_utils_cargo_bin::cargo_bin("hepta-notes-thread-seed")?)
            .output()?;
    anyhow::ensure!(!output.status.success());
    anyhow::ensure!(output.stdout.is_empty());
    anyhow::ensure!(
        String::from_utf8_lossy(&output.stderr)
            .contains("Original Notes thread seeding requires Linux")
    );
    Ok(())
}
