#![cfg(unix)]

use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::ProcessStream;
use tokio::time::timeout;

mod support;

use support::fleet::FleetHarness;

#[tokio::test]
async fn readiness_reports_exited_child_with_bounded_decoded_output() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "workspace-startup-diagnostic",
    )?;
    let allow_exit = agent.workspace.join("allow-child-exit");
    let command = AgentCommand::new(
        Path::new("/bin/sh").canonicalize()?,
        vec![
            "-c".into(),
            r#"printf '%05000d' 0
printf '\377stdout diagnostic marker\n'
printf '%05000d' 0 >&2
printf '\377stderr startup failure marker\n' >&2
while [ ! -f "$1" ]; do sleep 0.01; done
exit 17"#
                .into(),
            "fleet-readiness-fixture".into(),
            allow_exit.clone().into_os_string(),
        ],
    )?;
    fleet
        .supervisor
        .start(&agent.agent_id, command, Instant::now())?;

    // Hold the child alive until both output streams have reached the
    // supervisor. This avoids a race between pipe readers and child exit.
    timeout(Duration::from_secs(5), async {
        loop {
            let report = fleet.supervisor.tick(Instant::now());
            ensure!(report.faults.is_empty(), "unexpected faults: {report:?}");
            let snapshot = fleet
                .supervisor
                .snapshot(&agent.agent_id)
                .context("fixture snapshot missing")?;
            let [stdout, stderr] = [ProcessStream::Stdout, ProcessStream::Stderr].map(|stream| {
                snapshot
                    .logs
                    .iter()
                    .filter(|log| log.stream == stream)
                    .flat_map(|log| log.bytes.iter().copied())
                    .collect::<Vec<_>>()
            });
            if stdout.ends_with(b"stdout diagnostic marker\n")
                && stderr.ends_with(b"stderr startup failure marker\n")
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await
    .context("fixture output was not captured")??;
    std::fs::write(&allow_exit, b"exit")?;

    let outcome = timeout(
        Duration::from_secs(5),
        fleet.wait_ready(&agent, /*generation*/ 1),
    )
    .await
    .context("terminal child exit must not consume the readiness timeout")?;
    let error = outcome
        .err()
        .context("an exited child must fail readiness")?;
    let diagnostic = format!("{error:#}");
    ensure!(
        diagnostic.contains("failed before readiness"),
        "{diagnostic}"
    );
    ensure!(diagnostic.contains("code: Some(17)"), "{diagnostic}");
    ensure!(diagnostic.contains("last_health="), "{diagnostic}");
    let (_, output) = diagnostic
        .split_once("stdout (tail, max 4096 bytes):\n")
        .context("stdout diagnostic missing")?;
    let (stdout, stderr) = output
        .split_once("\nstderr (tail, max 4096 bytes):\n")
        .context("stderr diagnostic missing")?;
    ensure!(stdout.len() <= 4096 && stderr.len() <= 4096, "{diagnostic}");
    ensure!(
        stdout.ends_with("\u{fffd}stdout diagnostic marker\n"),
        "{diagnostic}"
    );
    ensure!(
        stderr.ends_with("\u{fffd}stderr startup failure marker\n"),
        "{diagnostic}"
    );
    let registry = fleet.registry.load()?;
    let record = registry
        .agent(&agent.agent_id)
        .context("fixture agent missing")?;
    ensure!(record.lifecycle.lifecycle == AgentLifecycle::Failed);
    Ok(())
}
