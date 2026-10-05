//! Bounded subprocess protocol; semantic tokenizer qualification is separate.
//!
//! The deadline covers stdin, stdout and process exit together. Stdout is read
//! concurrently with stdin so a child cannot deadlock the host by filling its
//! output pipe before it consumes a large request. No child output is logged.

use std::process::Stdio;
use std::time::Duration;

use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

use super::ExactContextDeliveryError;

pub(super) async fn run(
    command: &mut Command,
    request: &[u8],
    deadline: Duration,
    maximum_output_bytes: u64,
) -> Result<Vec<u8>, ExactContextDeliveryError> {
    if deadline.is_zero() || maximum_output_bytes == 0 || maximum_output_bytes > 4096 {
        return Err(ExactContextDeliveryError::TokenizerConfiguration);
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
    let execution = async {
        let mut stdin = child
            .stdin
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        let stdout = child
            .stdout
            .take()
            .ok_or(ExactContextDeliveryError::TokenizerUnavailable)?;
        let write = async {
            stdin
                .write_all(request)
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            stdin
                .shutdown()
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            drop(stdin);
            Ok::<_, ExactContextDeliveryError>(())
        };
        let read = async {
            let mut output = Vec::new();
            stdout
                .take(maximum_output_bytes + 1)
                .read_to_end(&mut output)
                .await
                .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
            if u64::try_from(output.len()).unwrap_or(u64::MAX) > maximum_output_bytes {
                return Err(ExactContextDeliveryError::TokenizerRejected);
            }
            Ok::<_, ExactContextDeliveryError>(output)
        };
        let ((), output) = tokio::try_join!(write, read)?;
        let status = child
            .wait()
            .await
            .map_err(|_| ExactContextDeliveryError::TokenizerUnavailable)?;
        if !status.success() {
            return Err(ExactContextDeliveryError::TokenizerRejected);
        }
        Ok(output)
    };
    let result = match timeout(deadline, execution).await {
        Ok(result) => result,
        Err(_) => Err(ExactContextDeliveryError::TokenizerTimeout),
    };
    if result.is_err() {
        // Do not allow cleanup to turn the bounded protocol into an unbounded
        // wait. Cancellation still has Tokio's kill-on-drop fallback.
        let _ = child.start_kill();
        let _ = timeout(Duration::from_secs(5), child.wait()).await;
    }
    result
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[tokio::test]
    async fn timeout_includes_a_child_that_never_reads_stdin() {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "exec sleep 3"]);
        let input = vec![b'x'; 1024 * 1024];
        let result = run(&mut command, &input, Duration::from_millis(50), 64).await;
        assert_eq!(result, Err(ExactContextDeliveryError::TokenizerTimeout));
    }

    #[tokio::test]
    async fn stdout_overflow_is_rejected_before_waiting_for_exit() {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "printf '12345678901234567890123456789012345678901234567890123456789012345678901'; exec sleep 3"]);
        let result = run(&mut command, b"", Duration::from_secs(1), 64).await;
        assert_eq!(result, Err(ExactContextDeliveryError::TokenizerRejected));
    }

    #[tokio::test]
    async fn stderr_and_exit_failure_are_not_token_evidence() {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "printf '17' >&2; exit 7"]);
        let result = run(&mut command, b"", Duration::from_secs(1), 64).await;
        assert_eq!(result, Err(ExactContextDeliveryError::TokenizerRejected));
    }

    #[tokio::test]
    async fn successful_stdout_is_returned_without_interpreting_it() {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "cat >/dev/null; printf '17\\n'"]);
        let result = run(&mut command, b"exact bytes", Duration::from_secs(1), 64).await;
        assert_eq!(result, Ok(b"17\n".to_vec()));
    }
}
