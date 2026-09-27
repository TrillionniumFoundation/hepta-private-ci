//! Exercise the shipped read-only observer against the real normal Agentd binary.
use std::path::Path;
use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;

pub async fn verify(socket: &Path, agent: &AgentId, generation: u64) -> Result<()> {
    let root = tempfile::tempdir()?;
    let script = root.path().join("ndu-observer.py");
    let output = root.path().join("ndu.prom");
    std::fs::write(
        &script,
        include_str!("../../../../scripts/hepta_ndu_observer.py"),
    )?;
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        tokio::process::Command::new("python3")
            .arg(script)
            .arg("--socket")
            .arg(socket)
            .arg("--agent-id")
            .arg(agent.as_str())
            .arg("--generation")
            .arg(generation.to_string())
            .arg("--output")
            .arg(&output)
            .kill_on_drop(true)
            .output(),
    )
    .await??;
    ensure!(
        result.status.success(),
        "normal Agentd observer failed: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    let text = std::fs::read_to_string(output)?;
    for (name, expected) in [
        ("observer_up", "1"),
        ("storage_ready", "1"),
        ("memory_fallback_total", "0"),
        ("backup_age_seconds_known", "0"),
    ] {
        let prefix = format!("hepta_ndu_{name}{{");
        let ending = format!("}} {expected}");
        ensure!(
            text.lines()
                .any(|line| line.starts_with(&prefix) && line.ends_with(&ending)),
            "observer did not preserve {name}"
        );
    }
    ensure!(!text.contains("hepta_ndu_backup_age_seconds{"));
    Ok(())
}
