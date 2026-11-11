use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use pretty_assertions::assert_eq;
use tokio::net::UnixDatagram;
use tokio::process::Command;
use tokio::signal::unix::SignalKind;
use tokio::signal::unix::signal;
use tokio::time::Instant;
use tokio::time::timeout_at;

use super::ShutdownSignals;
use crate::ShutdownSignal;

const FIXTURE_SIGNAL: &str = "CODEX_APP_SERVER_SHUTDOWN_SIGNAL_FIXTURE";
const FIXTURE_ACK: &str = "CODEX_APP_SERVER_SHUTDOWN_SIGNAL_ACK";
const CHILD_TEST: &str = "shutdown_signals::tests::retained_signal_child";

#[tokio::test]
async fn first_sigterm_survives_cancelled_receive() -> anyhow::Result<()> {
    run_retained_signal_child("TERM").await
}

#[tokio::test]
async fn first_sighup_survives_cancelled_receive() -> anyhow::Result<()> {
    run_retained_signal_child("HUP").await
}

#[tokio::test]
async fn first_sigint_survives_cancelled_receive() -> anyhow::Result<()> {
    run_retained_signal_child("INT").await
}

async fn run_retained_signal_child(signal_name: &str) -> anyhow::Result<()> {
    // Signal registration is process-wide. Only the owned fixture process
    // receives a signal; parallel tests in this process keep their own handlers.
    let stdout = tempfile::NamedTempFile::new()?;
    let stderr = tempfile::NamedTempFile::new()?;
    let private = tempfile::tempdir()?;
    let ack_path = private.path().join("signal-ack.sock");
    let ack = UnixDatagram::bind(&ack_path)?;
    let end = Instant::now() + Duration::from_secs(10);
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--exact", CHILD_TEST, "--ignored", "--test-threads=1"])
        .env(FIXTURE_SIGNAL, signal_name)
        .env(FIXTURE_ACK, &ack_path)
        .stdin(Stdio::null())
        .stdout(stdout.reopen()?)
        .stderr(stderr.reopen()?)
        .kill_on_drop(true)
        .spawn()?;
    let status = match timeout_at(end, child.wait()).await {
        Ok(status) => status?,
        Err(error) => {
            // Retain and reap the actual Child. No PID from a file is adopted.
            child.kill().await?;
            return Err(error).context("signal fixture exceeded its fixed process deadline");
        }
    };
    anyhow::ensure!(
        status.success(),
        "{signal_name} fixture failed with {status}; stdout={}; stderr={}",
        std::fs::read_to_string(stdout.path())?,
        std::fs::read_to_string(stderr.path())?,
    );
    // A libtest invocation selecting zero tests also exits successfully. Only
    // the actual fixture can acknowledge after both signal assertions pass.
    let mut received = [0u8; 64];
    let length = timeout_at(end, ack.recv(&mut received))
        .await
        .context("owned signal fixture did not acknowledge its assertions")??;
    assert_eq!(
        &received[..length],
        format!("retained:{signal_name}").as_bytes()
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "run by the three owned-child signal tests"]
async fn retained_signal_child() -> anyhow::Result<()> {
    let end = Instant::now() + Duration::from_secs(5);
    let signal_name = std::env::var(FIXTURE_SIGNAL).context("owned fixture selector missing")?;
    let ack_path = std::env::var_os(FIXTURE_ACK).context("owned fixture ACK endpoint missing")?;
    let (kind, expected) = match signal_name.as_str() {
        "TERM" => (SignalKind::terminate(), ShutdownSignal::Forceable),
        "HUP" => (SignalKind::hangup(), ShutdownSignal::GracefulOnly),
        "INT" => (SignalKind::interrupt(), ShutdownSignal::Forceable),
        _ => anyhow::bail!("invalid owned fixture signal"),
    };
    let mut retained = ShutdownSignals::register()?;
    let mut delivered = signal(kind)?;
    {
        let pending = retained.recv();
        tokio::pin!(pending);
        assert!(futures::poll!(pending.as_mut()).is_pending());
    }

    // One first signal is delivered while the main-loop receive future is
    // absent. The independent subscriber proves delivery before we recreate
    // that future, without relying on timing sleeps or libtest stdout markers.
    let status = timeout_at(
        end,
        Command::new("/bin/kill")
            .args(["-s", &signal_name, &std::process::id().to_string()])
            .kill_on_drop(true)
            .status(),
    )
    .await??;
    anyhow::ensure!(
        status.success(),
        "could not signal the owned fixture itself"
    );
    assert_eq!(timeout_at(end, delivered.recv()).await?, Some(()));
    assert_eq!(timeout_at(end, retained.recv()).await??, expected);
    let ack = UnixDatagram::unbound()?;
    ack.connect(ack_path)?;
    let message = format!("retained:{signal_name}");
    assert_eq!(
        timeout_at(end, ack.send(message.as_bytes())).await??,
        message.len()
    );
    Ok(())
}
