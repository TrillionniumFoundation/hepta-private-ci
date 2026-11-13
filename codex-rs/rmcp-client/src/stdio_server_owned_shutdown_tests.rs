//! Components for actual local processes and retained join handles.
//! These do not run an MCP handshake, carry phase authority, or prove a
//! complete Hepta shutdown. No completion or RootIntent fixture is forged.

use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

fn original_command(directory: &Path, script: &str) -> StdioServerCommand {
    StdioServerCommand::new(
        OsString::from("/bin/sh"),
        vec![OsString::from("-c"), OsString::from(script)],
        None,
        Vec::new(),
        Some(directory.to_string_lossy().into_owned()),
        McpProtocolMode::Legacy,
    )
}

async fn joined(
    custody: &OriginalStdioShutdownCustody,
) -> io::Result<OriginalStdioShutdownObservation> {
    tokio::time::timeout(Duration::from_secs(30), custody.join_original_stdio())
        .await
        .expect("actual child/helper cleanup did not finish")
}

async fn require_actual_handles_joined(custody: &OriginalStdioShutdownCustody) {
    let (launch, children, stderr, termination, termination_thread) = {
        let state = custody.state();
        (
            state.launch.clone().unwrap(),
            state.child.clone(),
            state.stderr.clone(),
            state.termination.clone().unwrap(),
            state._termination_thread.clone().unwrap(),
        )
    };
    {
        let state = launch.state.lock().await;
        assert!(state.joined);
        assert!(launch.completion.peek().is_some());
        assert!(
            state.result.is_none(),
            "actual transport must leave launch output"
        );
    }
    assert_eq!(children.len(), 1);
    assert_eq!(stderr.len(), 1);
    for child in children {
        let state = child.state.lock().await;
        assert!(state.joined);
        assert!(child.completion.peek().is_some());
        assert!(matches!(state.result.as_ref(), Some(Ok(_))));
    }
    for reader in stderr {
        let state = reader.state.lock().await;
        assert!(state.joined);
        assert!(reader.completion.peek().is_some());
    }
    let state = termination.state.lock().await;
    assert!(state.joined);
    assert!(termination.completion.peek().is_some());
    assert!(matches!(state.result.as_ref(), Some(Ok(()))));
    assert!(
        termination_thread.lock().unwrap().is_none(),
        "the actual std::thread::JoinHandle must have been consumed by join"
    );
}

#[tokio::test]
async fn empty_custody_cannot_attest_a_child_exit_or_start_after_stop() {
    let custody = OriginalStdioShutdownCustody::new();
    let observation = joined(&custody).await.unwrap();
    assert!(observation.require_original_child_exited().is_err());
    let directory = tempfile::tempdir().unwrap();
    let launcher = LocalStdioServerLauncher::new_with_owned_shutdown(
        directory.path().to_path_buf(),
        Arc::clone(&custody),
    );
    assert!(
        launcher
            .launch(original_command(directory.path(), "exit 0"))
            .await
            .is_err()
    );
    assert!(custody.state().launch.is_none());
}

#[tokio::test]
async fn unsupported_modern_mode_refuses_before_an_actual_launch() {
    let custody = OriginalStdioShutdownCustody::new();
    let directory = tempfile::tempdir().unwrap();
    let launcher = LocalStdioServerLauncher::new_with_owned_shutdown(
        directory.path().to_path_buf(),
        Arc::clone(&custody),
    );
    let mut command = original_command(directory.path(), "exit 0");
    command.protocol_mode = McpProtocolMode::V20260728;
    let error = match launcher.launch(command).await {
        Err(error) => error,
        Ok(transport) => {
            drop(transport);
            panic!("strict modern launch must refuse");
        }
    };
    assert_eq!(error.kind(), io::ErrorKind::Unsupported);
    assert!(custody.state().launch.is_none());
    assert!(
        joined(&custody)
            .await
            .unwrap()
            .require_original_child_exited()
            .is_err()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoned_actual_launch_output_is_taken_and_its_child_reaped() {
    let custody = OriginalStdioShutdownCustody::new();
    let directory = tempfile::tempdir().unwrap();
    // Use the same concrete start path without consuming its actual output:
    // this is the state left by cancellation of the launch waiter.
    let launch = custody
        .start_launch(
            original_command(
                directory.path(),
                "printf 'original-stderr\\n' >&2; exec sleep 30",
            ),
            directory.path().to_path_buf(),
        )
        .unwrap();
    {
        let state = launch.join().await;
        assert!(matches!(state.result.as_ref(), Some(Ok(_))));
    }
    let original_pid = custody.state().process_id.unwrap();

    let observation = joined(&custody).await.unwrap();
    observation.require_original_child_exited().unwrap();
    assert_eq!(observation.process_id, Some(original_pid));
    require_actual_handles_joined(&custody).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_cleanup_waiter_keeps_the_same_undropped_transport_and_jobs() {
    let custody = OriginalStdioShutdownCustody::new();
    let directory = tempfile::tempdir().unwrap();
    let launcher = LocalStdioServerLauncher::new_with_owned_shutdown(
        directory.path().to_path_buf(),
        Arc::clone(&custody),
    );
    let transport = launcher
        .launch(original_command(directory.path(), "exec sleep 30"))
        .await
        .unwrap();
    let original_pid = custody.state().process_id.unwrap();

    let mut cleanup = Box::pin(custody.join_original_stdio());
    tokio::select! {
        biased;
        result = &mut cleanup => {
            panic!("cleanup cannot finish while the actual transport remains owned: {}", result.is_ok());
        }
        () = async {} => {}
    }
    assert!(custody.state().child.is_empty());
    drop(cleanup);
    // Cancelling the waiter above does not consume the retained handles.
    // Only this real transport Drop returns the same actual child to custody.
    drop(transport);
    let observation = joined(&custody).await.unwrap();
    observation.require_original_child_exited().unwrap();
    assert_eq!(observation.process_id, Some(original_pid));
    require_actual_handles_joined(&custody).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_stderr_error_is_preserved_after_child_and_helper_joins() {
    let custody = OriginalStdioShutdownCustody::new();
    let directory = tempfile::tempdir().unwrap();
    let launcher = LocalStdioServerLauncher::new_with_owned_shutdown(
        directory.path().to_path_buf(),
        Arc::clone(&custody),
    );
    let transport = launcher
        .launch(original_command(
            directory.path(),
            "printf '\\377\\n' >&2; exec sleep 30",
        ))
        .await
        .unwrap();
    let reader = custody.state().stderr[0].clone();
    {
        let actual_read = tokio::time::timeout(Duration::from_secs(30), reader.join())
            .await
            .expect("original invalid UTF-8 stderr was not read");
        assert!(matches!(actual_read.result.as_ref(), Some(Err(_))));
    }

    drop(transport);
    let error = match joined(&custody).await {
        Err(error) => error,
        Ok(_) => panic!("actual stderr failure must not turn into successful shutdown"),
    };
    assert!(error.to_string().contains("stderr"));
    require_actual_handles_joined(&custody).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_sdk_send_future_cannot_keep_the_closed_actual_writer_live() {
    let custody = OriginalStdioShutdownCustody::new();
    let directory = tempfile::tempdir().unwrap();
    let launcher = LocalStdioServerLauncher::new_with_owned_shutdown(
        directory.path().to_path_buf(),
        Arc::clone(&custody),
    );
    let mut transport = launcher
        .launch(original_command(directory.path(), "exec sleep 30"))
        .await
        .unwrap();
    let message: TxJsonRpcMessage<RoleClient> =
        serde_json::from_str(r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#).unwrap();
    // This actual SDK future retains its write Arc but has not sent anything.
    // A mere AsyncRw Drop would leave its Writer inside that Arc.
    let pending_send: BoxFuture<'static, io::Result<()>> = transport.send(message).boxed();
    drop(transport);
    let observation = joined(&custody).await.unwrap();
    observation.require_original_child_exited().unwrap();
    let error = pending_send.await.unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::NotConnected);
    require_actual_handles_joined(&custody).await;
}

#[tokio::test]
async fn cancelled_shared_job_waiter_keeps_one_non_clone_fd_output_for_all_waiters() {
    use std::io::Read;
    use std::os::unix::net::UnixStream;

    let (owner, mut peer) = UnixStream::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let (release, released) = tokio::sync::oneshot::channel::<()>();
    let job = OwnedJob::track(tokio::spawn(async move {
        released
            .await
            .map_err(|_| io::Error::other("component release sender dropped"))?;
        Ok(owner)
    }));

    let mut cancelled = Box::pin(job.join());
    tokio::select! {
        biased;
        _ = &mut cancelled => panic!("actual handle cannot join before its release"),
        () = async {} => {}
    }
    drop(cancelled);
    assert!(job.completion.peek().is_none());
    let mut byte = [0_u8; 1];
    assert_eq!(
        peer.read(&mut byte).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );

    release.send(()).unwrap();
    tokio::join!(
        async {
            let state = job.join().await;
            assert!(state.joined);
            assert!(matches!(state.result.as_ref(), Some(Ok(_))));
        },
        async {
            let state = job.join().await;
            assert!(state.joined);
            assert!(matches!(state.result.as_ref(), Some(Ok(_))));
        },
    );
    assert!(job.completion.peek().is_some());
    let actual = {
        let mut state = job.state.lock().await;
        state.result.take().unwrap().unwrap()
    };
    assert!(job.state.lock().await.result.is_none());
    assert_eq!(
        peer.read(&mut byte).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
    drop(actual);
    assert_eq!(peer.read(&mut byte).unwrap(), 0);
}

#[tokio::test]
async fn shared_job_keeps_the_same_original_join_error_for_later_waiters() {
    let job = OwnedJob::<()>::track(tokio::spawn(async {
        panic!("original owned job component panic")
    }));
    let first = {
        let state = job.join().await;
        assert!(state.joined);
        state.result.as_ref().unwrap().as_ref().unwrap_err().clone()
    };
    let second = {
        let state = job.join().await;
        assert!(state.joined);
        state.result.as_ref().unwrap().as_ref().unwrap_err().clone()
    };
    assert!(Arc::ptr_eq(&first.error, &second.error));
    assert!(
        first
            .error
            .downcast_ref::<tokio::task::JoinError>()
            .unwrap()
            .is_panic()
    );
    assert!(job.completion.peek().is_some());
}
