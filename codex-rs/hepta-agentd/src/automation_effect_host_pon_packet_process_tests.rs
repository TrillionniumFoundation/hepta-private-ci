use super::Outcome;
use super::run_packet;
use std::path::Path;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

fn marker_command(marker: &Path, script: &str) -> Command {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", script, "hepta-owned-packet-test"]);
    command.arg(marker);
    command
}

#[tokio::test]
async fn packet_process_expired_before_entry_creates_no_child_marker() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let marker = root.path().join("expired.marker");
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(
        Instant::now(),
        CancellationToken::new(),
    );
    let outcome = run_packet(
        marker_command(&marker, "printf started > \"$1\"; exec /bin/cat"),
        b"complete-packet",
        Instant::now() + Duration::from_secs(/*secs*/ 30),
        super::super::MAX_PON_PROCESS_OUTPUT_BYTES,
        &execution,
    )
    .await;
    assert!(matches!(outcome, Outcome::BeforeStart));
    assert!(!marker.exists());
    Ok(())
}

#[tokio::test]
async fn packet_process_cancelled_before_entry_creates_no_child_marker() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let marker = root.path().join("cancelled.marker");
    let cancellation = CancellationToken::new();
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 30);
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(deadline, cancellation.clone());
    cancellation.cancel();
    let outcome = run_packet(
        marker_command(&marker, "printf started > \"$1\"; exec /bin/cat"),
        b"complete-packet",
        deadline,
        super::super::MAX_PON_PROCESS_OUTPUT_BYTES,
        &execution,
    )
    .await;
    assert!(matches!(outcome, Outcome::BeforeStart));
    assert!(!marker.exists());
    Ok(())
}

#[tokio::test]
async fn packet_process_preserves_complete_stdin_and_output() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let marker = root.path().join("complete.marker");
    let payload = (0_u8..=255).cycle().take(49_508).collect::<Vec<_>>();
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 30);
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(deadline, CancellationToken::new());
    let outcome = run_packet(
        marker_command(&marker, "printf started > \"$1\"; exec /bin/cat"),
        &payload,
        deadline,
        super::super::MAX_PON_PROCESS_OUTPUT_BYTES,
        &execution,
    )
    .await;
    let Outcome::Complete(stdout) = outcome else {
        anyhow::bail!("complete packet subprocess did not return a complete observation");
    };
    assert_eq!(stdout, payload);
    assert_eq!(std::fs::read(&marker)?, b"started");
    Ok(())
}

#[tokio::test]
async fn packet_process_cancelled_after_entry_is_unknown_and_reaps_owned_child()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let marker = root.path().join("owned-child.pid");
    let cancellation = CancellationToken::new();
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 30);
    let execution = crate::NeuralCognitiveExecutionV1::with_deadline(deadline, cancellation.clone());
    // exec preserves the observed shell PID and creates no descendant tree.
    let mut running = Box::pin(run_packet(
        marker_command(&marker, "printf '%s\\n' \"$$\" > \"$1\"; exec /bin/sleep 30"),
        b"complete-packet",
        deadline,
        super::super::MAX_PON_PROCESS_OUTPUT_BYTES,
        &execution,
    ));
    let observed = tokio::select! {
        _ = &mut running => anyhow::bail!("owned child ended before cancellation was issued"),
        observed = tokio::time::timeout(Duration::from_secs(/*secs*/ 2), async {
            loop {
                if let Ok(bytes) = tokio::fs::read(&marker).await
                    && let Ok(text) = std::str::from_utf8(&bytes)
                    && let Ok(pid) = text.trim().parse::<u32>()
                    && pid > 1
                {
                    break pid;
                }
                tokio::time::sleep(Duration::from_millis(/*millis*/ 5)).await;
            }
        }) => observed,
    };
    // Even a marker-observation failure must cancel and clean up this child.
    cancellation.cancel();
    let outcome = tokio::time::timeout(Duration::from_secs(/*secs*/ 2), &mut running).await?;
    let pid = observed?;
    assert!(matches!(outcome, Outcome::Unknown));
    // This signal-0 probe targets only the child PID read from this test's own
    // private marker; it does not send a terminating signal or inspect others.
    let still_present = Command::new("/bin/sh")
        .args(["-c", "kill -0 \"$1\" 2>/dev/null", "hepta-owned-child-probe"])
        .arg(pid.to_string())
        .status()?;
    assert!(!still_present.success(), "owned child remained after cancellation cleanup");
    Ok(())
}
