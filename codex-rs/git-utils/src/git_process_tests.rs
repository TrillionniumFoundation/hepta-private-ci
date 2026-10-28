use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
use std::future::poll_fn;
use std::io::Read;
use std::pin::Pin;
#[cfg(windows)]
use std::process::Stdio;
use std::task::Poll;
use std::time::Duration;
use tokio::io::AsyncRead;
use tokio::io::ReadBuf;
use tokio::process::Command;
use tokio::time::Instant;

const READINESS_OUTPUT_LIMIT: usize = 4_096;
const READINESS_DIAGNOSTIC_TIMEOUT: Duration = Duration::from_millis(/*millis*/ 250);

#[derive(Debug, PartialEq, Eq)]
struct ReadinessOutput {
    bytes: Vec<u8>,
    status: String,
}

async fn read_readiness_output(
    pipe: Option<impl AsyncRead + Unpin>,
    deadline: Instant,
) -> ReadinessOutput {
    let Some(mut pipe) = pipe else {
        return ReadinessOutput {
            bytes: Vec::new(),
            status: "incomplete_missing_pipe".to_string(),
        };
    };
    let mut bytes = Vec::with_capacity(READINESS_OUTPUT_LIMIT + 1);
    let mut buffer = [0; 1_024];
    let status = loop {
        let available = (READINESS_OUTPUT_LIMIT + 1 - bytes.len()).min(buffer.len());
        let read = poll_fn(|cx| {
            let mut read_buf = ReadBuf::new(&mut buffer[..available]);
            match Pin::new(&mut pipe).poll_read(cx, &mut read_buf) {
                Poll::Ready(Ok(())) => Poll::Ready(Ok(read_buf.filled().len())),
                Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            }
        });
        match tokio::time::timeout_at(deadline, read).await {
            Ok(Ok(0)) => break "complete_eof".to_string(),
            Ok(Ok(count)) => {
                bytes.extend_from_slice(&buffer[..count]);
                if bytes.len() > READINESS_OUTPUT_LIMIT {
                    bytes.truncate(READINESS_OUTPUT_LIMIT);
                    break "incomplete_truncated".to_string();
                }
            }
            Ok(Err(error)) => break format!("incomplete_read_error: {error:?}"),
            Err(_) => break "incomplete_diagnostic_deadline_elapsed".to_string(),
        }
    };
    ReadinessOutput { bytes, status }
}

#[derive(Clone, Copy)]
enum GitWrapperLifetime {
    WaitForChild,
    ExitBeforeTimeout,
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    let temp_dir = tempfile::tempdir().expect("create temp dir");
    let child_pid_file = temp_dir.path().join("child.pid");
    let child_ready_file = temp_dir.path().join("child-ready");
    let release_child_file = temp_dir.path().join("release-child");
    let child_survived_file = temp_dir.path().join("child-survived");
    let release_wrapper_file = temp_dir.path().join("release-wrapper");
    #[cfg(unix)]
    let mut command = {
        let mut command = Command::new("/bin/sh");
        let wrapper_command = match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => {
                r#"( : > "$CHILD_READY_FILE"; while [ ! -f "$RELEASE_CHILD_FILE" ]; do sleep 0.01; done; sleep 1; : > "$CHILD_SURVIVED_FILE"; sleep 60 ) & child_pid=$!; printf '%s\n' "$child_pid" > "$CHILD_PID_FILE"; wait "$child_pid""#
            }
            GitWrapperLifetime::ExitBeforeTimeout => {
                r#"( : > "$CHILD_READY_FILE"; while [ ! -f "$RELEASE_CHILD_FILE" ]; do sleep 0.01; done; sleep 1; : > "$CHILD_SURVIVED_FILE"; sleep 60 ) & child_pid=$!; printf '%s\n' "$child_pid" > "$CHILD_PID_FILE"; while [ ! -f "$RELEASE_WRAPPER_FILE" ]; do sleep 0.01; done"#
            }
        };
        command.args(["-c", wrapper_command]);
        command
    };
    #[cfg(windows)]
    let mut command = {
        let mut command = Command::new("powershell.exe");
        let child_command = "Set-Content -LiteralPath $env:CHILD_READY_FILE -Value ready; while (-not (Test-Path $env:RELEASE_CHILD_FILE)) { Start-Sleep -Milliseconds 25 }; Start-Sleep -Seconds 1; Set-Content -LiteralPath $env:CHILD_SURVIVED_FILE -Value survived; Start-Sleep -Seconds 60";
        let wrapper_command = match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => format!(
                "$child = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-Command', '{child_command}') -PassThru -NoNewWindow; [System.IO.File]::WriteAllText($env:CHILD_PID_FILE, [string]$child.Id); Wait-Process -Id $child.Id"
            ),
            GitWrapperLifetime::ExitBeforeTimeout => format!(
                "$child = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-Command', '{child_command}') -PassThru -NoNewWindow; [System.IO.File]::WriteAllText($env:CHILD_PID_FILE, [string]$child.Id); while (-not (Test-Path $env:RELEASE_WRAPPER_FILE)) {{ Start-Sleep -Milliseconds 25 }}"
            ),
        };
        command
            .args(["-NoProfile", "-NonInteractive", "-Command"])
            .arg(wrapper_command);
        command
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let child_pid = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break child_pid.trim().to_string();
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match child_pid {
        Ok(child_pid) => child_pid,
        Err(readiness_error) => {
            let wrapper_pid = wrapper.id();
            let wrapper_exit = wrapper.try_wait();
            let child_pid_file_len = std::fs::metadata(&child_pid_file).map(|file| file.len());
            let child_ready_exists = child_ready_file.try_exists();
            let child_pid_read = std::fs::File::open(&child_pid_file).and_then(|file| {
                let mut bytes = Vec::with_capacity(/*capacity*/ 129);
                file.take(/*limit*/ 129).read_to_end(&mut bytes)?;
                if bytes.len() > 128 {
                    return Ok(
                        "truncated_after_128_bytes; trimmed_nonempty=unknown; parsed_pid=unknown"
                            .to_string(),
                    );
                }
                Ok(match std::str::from_utf8(&bytes) {
                    Ok(text) => format!(
                        "trimmed_nonempty={}; parsed_pid={:?}",
                        !text.trim().is_empty(),
                        text.trim().parse::<u32>(),
                    ),
                    Err(error) => format!("invalid_utf8; readiness_condition=false; {error:?}"),
                })
            });
            let stdout = wrapper.stdout.take();
            let stderr = wrapper.stderr.take();
            // Preserve the normal path and its pipe backpressure. Only after the
            // readiness failure, run the original cleanup before draining output.
            drop(process_tree);
            drop(wrapper);
            let diagnostic_deadline = Instant::now() + READINESS_DIAGNOSTIC_TIMEOUT;
            let (stdout, stderr) = tokio::join!(
                read_readiness_output(stdout, diagnostic_deadline),
                read_readiness_output(stderr, diagnostic_deadline),
            );
            panic!(
                "wait for Git wrapper child readiness: {readiness_error:?}; \
                 wrapper_pid={wrapper_pid:?}; wrapper_exit={wrapper_exit:?}; \
                 child_pid_file_len={child_pid_file_len:?}; child_pid_read={child_pid_read:?}; \
                 child_ready_exists={child_ready_exists:?}; \
                 diagnostic_window_ms=250; retained_limit_per_stream=4096; \
                 stdout_status={:?}; stdout={:?}; stderr_status={:?}; stderr={:?}",
                stdout.status,
                String::from_utf8_lossy(&stdout.bytes),
                stderr.status,
                String::from_utf8_lossy(&stderr.bytes),
            );
        }
    };

    if matches!(wrapper_lifetime, GitWrapperLifetime::ExitBeforeTimeout) {
        std::fs::write(&release_wrapper_file, "release").expect("release Git wrapper");
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if wrapper
                    .try_wait()
                    .expect("check Git wrapper state")
                    .is_some()
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .expect("wait for Git wrapper exit");
    }

    let output =
        wait_for_git_command_with_timeout_output(wrapper, process_tree, Duration::from_millis(100))
            .await;
    assert_eq!(output, None);

    std::fs::write(&release_child_file, "release").expect("release Git wrapper child");
    tokio::time::sleep(Duration::from_secs(3)).await;
    if !child_survived_file.exists() {
        return;
    }

    #[cfg(unix)]
    let _ = std::process::Command::new("kill")
        .args(["-KILL", &child_pid])
        .status();
    #[cfg(windows)]
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &child_pid, "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    panic!("Git wrapper child process {child_pid} survived timeout cleanup");
}

#[tokio::test]
async fn timed_out_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::WaitForChild,
    )
    .await;
}

#[tokio::test]
async fn timed_out_exited_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::ExitBeforeTimeout,
    )
    .await;
}

#[derive(Clone, Copy)]
enum ReadinessTestEnd {
    Eof,
    Pending,
    Error,
}

struct ReadinessTestPipe {
    bytes: Vec<u8>,
    offset: usize,
    end: ReadinessTestEnd,
}

impl AsyncRead for ReadinessTestPipe {
    fn poll_read(
        self: Pin<&mut Self>,
        _cx: &mut std::task::Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        let pipe = self.get_mut();
        if pipe.offset < pipe.bytes.len() {
            let end = (pipe.offset + buffer.remaining()).min(pipe.bytes.len());
            buffer.put_slice(&pipe.bytes[pipe.offset..end]);
            pipe.offset = end;
            return Poll::Ready(Ok(()));
        }
        match pipe.end {
            ReadinessTestEnd::Eof => Poll::Ready(Ok(())),
            ReadinessTestEnd::Pending => Poll::Pending,
            ReadinessTestEnd::Error => {
                Poll::Ready(Err(std::io::Error::other("diagnostic test error")))
            }
        }
    }
}

#[tokio::test]
async fn readiness_output_distinguishes_exact_limit_from_truncation() {
    for input_len in [0, READINESS_OUTPUT_LIMIT, READINESS_OUTPUT_LIMIT + 1] {
        let pipe = ReadinessTestPipe {
            bytes: vec![b'x'; input_len],
            offset: 0,
            end: ReadinessTestEnd::Eof,
        };
        let actual =
            read_readiness_output(Some(pipe), Instant::now() + READINESS_DIAGNOSTIC_TIMEOUT).await;
        assert_eq!(
            actual,
            ReadinessOutput {
                bytes: vec![b'x'; input_len.min(READINESS_OUTPUT_LIMIT)],
                status: if input_len > READINESS_OUTPUT_LIMIT {
                    "incomplete_truncated".to_string()
                } else {
                    "complete_eof".to_string()
                },
            },
        );
    }
}

#[tokio::test]
async fn readiness_output_preserves_partial_bytes_on_shared_deadline() {
    // timeout_at polls a ready read before its timer even at an expired deadline.
    // Start at that boundary: bytes and EOF must survive, while Pending expires.
    let deadline = Instant::now();
    let (pending, complete) = tokio::join!(
        read_readiness_output(
            Some(ReadinessTestPipe {
                bytes: b"before pending".to_vec(),
                offset: 0,
                end: ReadinessTestEnd::Pending,
            }),
            deadline,
        ),
        read_readiness_output(
            Some(ReadinessTestPipe {
                bytes: b"other stream".to_vec(),
                offset: 0,
                end: ReadinessTestEnd::Eof,
            }),
            deadline,
        ),
    );
    assert_eq!(
        pending,
        ReadinessOutput {
            bytes: b"before pending".to_vec(),
            status: "incomplete_diagnostic_deadline_elapsed".to_string(),
        },
    );
    assert_eq!(
        complete,
        ReadinessOutput {
            bytes: b"other stream".to_vec(),
            status: "complete_eof".to_string(),
        },
    );
}

#[tokio::test]
async fn readiness_output_preserves_read_error_and_missing_pipe() {
    let deadline = Instant::now() + READINESS_DIAGNOSTIC_TIMEOUT;
    let actual = read_readiness_output(
        Some(ReadinessTestPipe {
            bytes: b"before error".to_vec(),
            offset: 0,
            end: ReadinessTestEnd::Error,
        }),
        deadline,
    )
    .await;
    assert_eq!(
        actual,
        ReadinessOutput {
            bytes: b"before error".to_vec(),
            status: format!(
                "incomplete_read_error: {:?}",
                std::io::Error::other("diagnostic test error"),
            ),
        },
    );
    assert_eq!(
        read_readiness_output(/*pipe*/ None::<ReadinessTestPipe>, deadline).await,
        ReadinessOutput {
            bytes: Vec::new(),
            status: "incomplete_missing_pipe".to_string(),
        },
    );
}
