use super::UNIFIED_EXEC_OUTPUT_MAX_BYTES;
use super::process::NoopSpawnLifecycle;
use super::process::UnifiedExecProcess;
use super::process_manager::UnifiedExecProcessManager;
use codex_sandboxing::SandboxType;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::time::Duration;
use tokio::time::Instant;

async fn local_process() -> anyhow::Result<(
    UnifiedExecProcess,
    broadcast::Sender<Vec<u8>>,
    tokio::sync::oneshot::Sender<i32>,
)> {
    let (writer_tx, _writer_rx) = tokio::sync::mpsc::channel(1);
    let (stdout_tx, stdout_rx) = broadcast::channel(8);
    let (exit_tx, exit_rx) = tokio::sync::oneshot::channel();
    let spawned = codex_utils_pty::spawn_from_driver(codex_utils_pty::ProcessDriver {
        writer_tx,
        stdout_rx,
        stderr_rx: None,
        exit_rx,
        terminator: None,
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    let process =
        UnifiedExecProcess::from_spawned(spawned, SandboxType::None, Box::new(NoopSpawnLifecycle))
            .await?;
    Ok((process, stdout_tx, exit_tx))
}

async fn send_and_collect(
    process: &UnifiedExecProcess,
    stdout_tx: &broadcast::Sender<Vec<u8>>,
    bytes: &[u8],
) -> Vec<u8> {
    stdout_tx
        .send(bytes.to_vec())
        .expect("send producer output");
    // Acknowledge each input so only the downstream delta receiver can lag.
    // This also exercises the real polling drain between every pair of chunks.
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if process
                .output_handles()
                .output_buffer
                .lock()
                .await
                .total_bytes()
                == bytes.len()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("producer should publish the current chunk");

    UnifiedExecProcessManager::collect_output_until_deadline(
        process.output_handles(),
        /*pause_state*/ None,
        Instant::now(),
    )
    .await
    .to_bytes()
}

#[tokio::test]
async fn cumulative_transcript_survives_delta_lag_and_polling_drains() -> anyhow::Result<()> {
    let (process, stdout_tx, exit_tx) = local_process().await?;
    let mut slow_deltas = process.output_receiver();
    let input = format!("HEAD\n{}TAIL\n", "token token \n".repeat(100_000)).into_bytes();
    let mut collected = Vec::new();
    for chunk in input.chunks(8192) {
        collected.extend(send_and_collect(&process, &stdout_tx, chunk).await);
    }
    assert_eq!(collected, input);
    assert!(matches!(
        slow_deltas.try_recv(),
        Err(broadcast::error::TryRecvError::Lagged(skipped)) if skipped > 0
    ));

    let retained = UNIFIED_EXEC_OUTPUT_MAX_BYTES;
    let omitted = input.len() - retained;
    let head = retained / 2;
    let tail = retained - head;
    let mut expected = input[..head].to_vec();
    expected.extend(format!("\n... {omitted} bytes omitted ...\n").as_bytes());
    expected.extend(&input[input.len() - tail..]);
    let transcript = process.output_handles().transcript.lock().await;
    assert_eq!(
        (
            transcript.total_bytes(),
            transcript.retained_bytes(),
            transcript.omitted_bytes(),
            transcript.to_bytes_with_omission_marker(),
        ),
        (input.len(), retained, omitted, expected)
    );
    drop(transcript);
    assert_eq!(
        process
            .output_handles()
            .output_buffer
            .lock()
            .await
            .total_bytes(),
        0
    );
    drop(stdout_tx);
    exit_tx.send(0).expect("send exit");
    Ok(())
}

#[tokio::test]
async fn cumulative_transcript_keeps_output_before_delta_subscription() -> anyhow::Result<()> {
    let (process, stdout_tx, exit_tx) = local_process().await?;
    assert_eq!(
        send_and_collect(&process, &stdout_tx, b"BEFORE\n").await,
        b"BEFORE\n"
    );
    let mut late_deltas = process.output_receiver();
    assert!(matches!(
        late_deltas.try_recv(),
        Err(broadcast::error::TryRecvError::Empty)
    ));
    assert_eq!(
        send_and_collect(&process, &stdout_tx, b"AFTER\n").await,
        b"AFTER\n"
    );
    assert_eq!(late_deltas.try_recv().expect("late delta"), b"AFTER\n");
    assert_eq!(
        process
            .output_handles()
            .transcript
            .lock()
            .await
            .to_bytes_with_omission_marker(),
        b"BEFORE\nAFTER\n"
    );
    drop(stdout_tx);
    exit_tx.send(0).expect("send exit");
    Ok(())
}
