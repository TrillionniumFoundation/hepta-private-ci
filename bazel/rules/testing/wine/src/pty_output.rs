use anyhow::Context;
use anyhow::Result;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

/// Drain concurrently without requiring EOF from handles owned by Wine helpers.
/// The caller must stop the isolated server, then drain the remaining output.
pub(super) async fn collect_until_exit(
    stdout_rx: &mut mpsc::Receiver<Vec<u8>>,
    stderr_rx: &mut mpsc::Receiver<Vec<u8>>,
    mut exit_rx: oneshot::Receiver<i32>,
    stdout: &mut Vec<u8>,
    stderr: &mut Vec<u8>,
) -> Result<i32> {
    let mut stdout_open = true;
    let mut stderr_open = true;
    loop {
        tokio::select! {
            result = &mut exit_rx => return result.context("wait for PowerShell"),
            chunk = stdout_rx.recv(), if stdout_open => match chunk {
                Some(chunk) => stdout.extend(chunk),
                None => stdout_open = false,
            },
            chunk = stderr_rx.recv(), if stderr_open => match chunk {
                Some(chunk) => stderr.extend(chunk),
                None => stderr_open = false,
            },
        }
    }
}

pub(super) async fn drain_output(
    stdout_rx: &mut mpsc::Receiver<Vec<u8>>,
    stderr_rx: &mut mpsc::Receiver<Vec<u8>>,
    stdout: &mut Vec<u8>,
    stderr: &mut Vec<u8>,
) {
    tokio::join!(
        async {
            while let Some(chunk) = stdout_rx.recv().await {
                stdout.extend(chunk);
            }
        },
        async {
            while let Some(chunk) = stderr_rx.recv().await {
                stderr.extend(chunk);
            }
        },
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::FutureExt;
    use pretty_assertions::assert_eq;

    #[tokio::test]
    async fn application_exit_precedes_helper_eof_and_preserves_tail_output() -> Result<()> {
        let (stdout_tx, mut stdout_rx) = mpsc::channel(2);
        let (stderr_tx, mut stderr_rx) = mpsc::channel(2);
        let (exit_tx, exit_rx) = oneshot::channel();
        stdout_tx.send(b"marker".to_vec()).await?;
        exit_tx
            .send(0)
            .map_err(|_| anyhow::anyhow!("exit receiver"))?;
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();

        let code = collect_until_exit(
            &mut stdout_rx,
            &mut stderr_rx,
            exit_rx,
            &mut stdout,
            &mut stderr,
        )
        .now_or_never()
        .context("application exit must not wait for the live helper's EOF")??;
        assert_eq!(code, 0);

        // Teardown can still produce bytes. Close the simulated helper's
        // handles only after application exit, then require exact full output.
        stdout_tx.send(b"-tail".to_vec()).await?;
        stderr_tx.send(b"diagnostic".to_vec()).await?;
        drop(stdout_tx);
        drop(stderr_tx);
        drain_output(&mut stdout_rx, &mut stderr_rx, &mut stdout, &mut stderr).await;
        assert_eq!(stdout, b"marker-tail");
        assert_eq!(stderr, b"diagnostic");
        Ok(())
    }
}
