use std::sync::Arc;
use std::sync::atomic::Ordering;

use super::Buffer;
use super::Emitter;
use super::TRAILING_OUTPUT_GRACE;
use super::resolve_aggregated_output;
use super::spawn_exit_watcher;
use super::start_streaming_output;
use super::utf8_boundary;
use crate::session::tests::make_session_and_context_with_rx;
use crate::unified_exec::UNIFIED_EXEC_OUTPUT_MAX_BYTES;
use crate::unified_exec::UnifiedExecContext;
use crate::unified_exec::UnifiedExecProcessManager;
use crate::unified_exec::head_tail_buffer::HeadTailBuffer;
use crate::unified_exec::process::NoopSpawnLifecycle;
use crate::unified_exec::process::UnifiedExecProcess;
use codex_protocol::items::CommandExecutionStatus;
use codex_protocol::items::TurnItem;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ExecCommandOutputDeltaEvent;
use codex_protocol::protocol::ExecOutputStream;
use codex_sandboxing::SandboxType;

use pretty_assertions::assert_eq;
use tokio::time::Duration;
use tokio::time::Instant;

struct StreamingOutputHarness {
    process: Arc<UnifiedExecProcess>,
    stdout_tx: tokio::sync::broadcast::Sender<Vec<u8>>,
    stderr_tx: tokio::sync::broadcast::Sender<Vec<u8>>,
    exit_tx: tokio::sync::oneshot::Sender<i32>,
    transcript: Arc<tokio::sync::Mutex<HeadTailBuffer>>,
    context: UnifiedExecContext,
    rx_event: async_channel::Receiver<Event>,
}

async fn streaming_output_harness() -> anyhow::Result<StreamingOutputHarness> {
    let harness = output_harness().await?;
    start_streaming_output(&harness.process, &harness.context);
    Ok(harness)
}

async fn output_harness() -> anyhow::Result<StreamingOutputHarness> {
    let (writer_tx, _writer_rx) = tokio::sync::mpsc::channel::<Vec<u8>>(1);
    let (stdout_tx, stdout_rx) = tokio::sync::broadcast::channel::<Vec<u8>>(8);
    let (stderr_tx, stderr_rx) = tokio::sync::broadcast::channel::<Vec<u8>>(8);
    let (exit_tx, exit_rx) = tokio::sync::oneshot::channel::<i32>();
    let spawned = codex_utils_pty::spawn_from_driver(codex_utils_pty::ProcessDriver {
        writer_tx,
        stdout_rx,
        stderr_rx: Some(stderr_rx),
        exit_rx,
        terminator: None,
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    let process = Arc::new(
        UnifiedExecProcess::from_spawned(spawned, SandboxType::None, Box::new(NoopSpawnLifecycle))
            .await?,
    );
    let (session, turn, rx_event) = make_session_and_context_with_rx().await;
    let context = UnifiedExecContext::new(
        session,
        crate::session::step_context::StepContext::for_test(turn),
        tokio_util::sync::CancellationToken::new(),
        "streaming-output-test".to_string(),
    );
    let transcript = process.transcript();

    Ok(StreamingOutputHarness {
        process,
        stdout_tx,
        stderr_tx,
        exit_tx,
        transcript,
        context,
        rx_event,
    })
}

#[tokio::test]
async fn output_transcript_survives_lagged_deltas_polling_and_late_output() -> anyhow::Result<()> {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        stderr_tx,
        exit_tx,
        transcript,
        context,
        ..
    } = output_harness().await?;
    let output = process.output_handles();
    let mut stalled_deltas = process.output_receiver();
    let mut prefix = b"HEAD\n\xff".to_vec();
    prefix.extend(vec![b'x'; 160 * 8192]);

    // Wait for the real output owner after each input, so only the deliberately
    // stalled delta subscriber can lag. No timing or channel-size change is needed.
    tokio::time::timeout(Duration::from_secs(5), async {
        for chunk in prefix.chunks(8192) {
            let received = output.output_notify.notified();
            tokio::pin!(received);
            received.as_mut().enable();
            stdout_tx.send(chunk.to_vec()).expect("send process output");
            received.await;
        }
    })
    .await?;
    assert!(matches!(
        stalled_deltas.try_recv(),
        Err(tokio::sync::broadcast::error::TryRecvError::Lagged(skipped)) if skipped > 0
    ));

    let first_poll = UnifiedExecProcessManager::collect_output_until_deadline(
        output,
        /*pause_state*/ None,
        Instant::now(),
    )
    .await;
    assert_eq!(first_poll.total_bytes(), prefix.len());

    drop(stdout_tx);
    exit_tx.send(0).expect("send exit before trailing output");
    process.cancellation_token().cancelled().await;
    let tail = b"TAIL\n\xc3";
    let received = output.output_notify.notified();
    tokio::pin!(received);
    received.as_mut().enable();
    stderr_tx.send(tail.to_vec()).expect("send trailing stderr");
    received.await;

    let closed = output.output_closed_notify.notified();
    tokio::pin!(closed);
    closed.as_mut().enable();
    drop(stderr_tx);
    if !output.output_closed.load(Ordering::Acquire) {
        closed.await;
    }
    let final_poll = UnifiedExecProcessManager::collect_output_until_deadline(
        output,
        /*pause_state*/ None,
        Instant::now(),
    )
    .await;
    assert_eq!(final_poll.to_bytes(), tail);

    // Even a subscriber attached after both exit and stream close must not
    // determine the retained transcript or reinsert already-polled bytes.
    start_streaming_output(&process, &context);
    process.output_drained_notify().notified().await;
    prefix.extend_from_slice(tail);
    let omitted = prefix.len() - UNIFIED_EXEC_OUTPUT_MAX_BYTES;
    let head_budget = UNIFIED_EXEC_OUTPUT_MAX_BYTES / 2;
    let mut expected = prefix[..head_budget].to_vec();
    expected.extend_from_slice(format!("\n... {omitted} bytes omitted ...\n").as_bytes());
    expected.extend_from_slice(&prefix[prefix.len() - head_budget..]);
    let retained = transcript.lock().await;
    assert_eq!(
        (
            retained.total_bytes(),
            retained.retained_bytes(),
            retained.omitted_bytes(),
            retained.to_bytes_with_omission_marker(),
        ),
        (
            prefix.len(),
            UNIFIED_EXEC_OUTPUT_MAX_BYTES,
            omitted,
            expected.clone(),
        )
    );
    drop(retained);
    assert_eq!(
        resolve_aggregated_output(&transcript, "fallback must not win".to_string()).await,
        String::from_utf8_lossy(&expected)
    );
    assert_eq!(output.output_buffer.lock().await.total_bytes(), 0);
    Ok(())
}

#[tokio::test]
async fn streaming_output_preserves_multibyte_characters_across_chunks() -> anyhow::Result<()> {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        exit_tx,
        transcript,
        rx_event,
        ..
    } = streaming_output_harness().await?;
    let output_drained = process.output_drained_notify();
    let drained = output_drained.notified();
    tokio::pin!(drained);

    stdout_tx.send(vec![0xc3]).expect("send UTF-8 lead byte");
    stdout_tx
        .send(vec![0xa9])
        .expect("send UTF-8 continuation byte");
    drop(stdout_tx);
    exit_tx.send(0).expect("send exit");
    (&mut drained).await;

    let event = rx_event.recv().await.expect("receive output delta");
    let EventMsg::ExecCommandOutputDelta(delta) = event.msg else {
        panic!("expected ExecCommandOutputDelta");
    };
    assert_eq!(
        delta,
        ExecCommandOutputDeltaEvent {
            call_id: "streaming-output-test".to_string(),
            stream: ExecOutputStream::Stdout,
            chunk: "é".as_bytes().to_vec(),
        }
    );
    assert_eq!(
        transcript.lock().await.to_bytes_with_omission_marker(),
        "é".as_bytes()
    );
    assert!(rx_event.try_recv().is_err());

    Ok(())
}

#[tokio::test]
async fn streaming_output_finishes_on_close_without_waiting_for_grace() -> anyhow::Result<()> {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        exit_tx,
        transcript,
        ..
    } = streaming_output_harness().await?;
    let output_drained = process.output_drained_notify();
    let drained = output_drained.notified();
    tokio::pin!(drained);

    tokio::time::pause();
    let exited_at = Instant::now();
    exit_tx.send(0).expect("send exit");
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(50)).await;
        stdout_tx
            .send(b"LATE-OUTPUT-MARKER\xc3".to_vec())
            .expect("send late output");
    });

    (&mut drained).await;
    let elapsed = Instant::now().saturating_duration_since(exited_at);
    tokio::time::resume();

    assert!(
        elapsed >= Duration::from_millis(50) && elapsed < TRAILING_OUTPUT_GRACE,
        "output close should finish before the grace fallback: {elapsed:?}"
    );
    assert_eq!(
        transcript.lock().await.to_bytes_with_omission_marker(),
        b"LATE-OUTPUT-MARKER\xc3"
    );

    Ok(())
}

#[tokio::test]
async fn streaming_output_keeps_grace_as_fallback_without_close() -> anyhow::Result<()> {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        exit_tx,
        transcript,
        rx_event,
        ..
    } = streaming_output_harness().await?;
    let output_drained = process.output_drained_notify();
    let drained = output_drained.notified();
    tokio::pin!(drained);

    tokio::time::pause();
    let exited_at = Instant::now();
    stdout_tx.send(vec![0xc3]).expect("send UTF-8 lead byte");
    exit_tx.send(0).expect("send exit");
    (&mut drained).await;
    let elapsed = Instant::now().saturating_duration_since(exited_at);
    tokio::time::resume();

    assert!(
        elapsed >= TRAILING_OUTPUT_GRACE
            && elapsed <= TRAILING_OUTPUT_GRACE + Duration::from_millis(10),
        "missing output close should use the grace fallback: {elapsed:?}"
    );
    assert_eq!(
        transcript.lock().await.to_bytes_with_omission_marker(),
        vec![0xc3]
    );
    let event = rx_event.try_recv().expect("receive final output delta");
    let EventMsg::ExecCommandOutputDelta(delta) = event.msg else {
        panic!("expected ExecCommandOutputDelta");
    };
    assert_eq!(
        delta,
        ExecCommandOutputDeltaEvent {
            call_id: "streaming-output-test".to_string(),
            stream: ExecOutputStream::Stdout,
            chunk: vec![0xc3],
        }
    );
    assert!(rx_event.try_recv().is_err());

    Ok(())
}

#[tokio::test]
async fn exit_watcher_waits_for_late_network_denial_before_classifying_end() -> anyhow::Result<()> {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        exit_tx,
        transcript,
        context,
        rx_event,
        ..
    } = streaming_output_harness().await?;

    tokio::time::pause();
    let process_for_late_denial = Arc::clone(&process);
    let (late_denial_armed_tx, late_denial_armed_rx) = tokio::sync::oneshot::channel();
    let network_denial_monitor = tokio::spawn(async move {
        let sleep = tokio::time::sleep(Duration::from_millis(10));
        tokio::pin!(sleep);
        late_denial_armed_tx.send(()).expect("arm late denial");
        sleep.await;
        process_for_late_denial.fail_and_terminate("LATE_DENIAL".to_string());
    });
    late_denial_armed_rx.await.expect("late denial armed");

    #[allow(deprecated)]
    let cwd = context.step_context.turn.cwd.clone().into();
    spawn_exit_watcher(
        Arc::clone(&process),
        Arc::clone(&context.session),
        Arc::clone(&context.step_context.turn),
        context.call_id,
        vec!["proof".to_string()],
        cwd,
        /*process_id*/ 123,
        /*plugin_attribution*/ None,
        transcript,
        Instant::now(),
        Some(network_denial_monitor),
        /*plugin_metrics_sidecar*/ None,
    );

    let exited_at = Instant::now();
    exit_tx.send(0).expect("send exit");
    drop(stdout_tx);

    let event = rx_event.recv().await.expect("command end event");
    let elapsed = Instant::now().saturating_duration_since(exited_at);
    tokio::time::resume();
    let EventMsg::ItemCompleted(completed) = event.msg else {
        panic!("expected ItemCompleted");
    };
    let TurnItem::CommandExecution(item) = completed.item else {
        panic!("expected CommandExecution");
    };
    assert_eq!(
        (
            item.status,
            item.exit_code,
            item.aggregated_output.as_deref()
        ),
        (
            CommandExecutionStatus::Failed,
            Some(-1),
            Some("LATE_DENIAL")
        )
    );
    assert!(
        elapsed >= Duration::from_millis(10) && elapsed < TRAILING_OUTPUT_GRACE,
        "completion should wait for denial without falling back to the output grace: {elapsed:?}"
    );

    Ok(())
}

#[test]
fn utf8_boundary_preserves_complete_characters() {
    assert_eq!(utf8_boundary(b"hello"), 5);

    let bytes = "ééé".as_bytes();
    assert_eq!(utf8_boundary(&bytes[..3]), 2);

    let bytes = "😀".as_bytes();
    assert_eq!(utf8_boundary(bytes), bytes.len());
    for len in 1..bytes.len() {
        assert_eq!(utf8_boundary(&bytes[..len]), 0);
    }
    assert_eq!(utf8_boundary(&[0xf0, 0x9f, 0x98, 0x80, 0xc3]), 4);
}

#[test]
fn utf8_boundary_batches_malformed_output() {
    assert_eq!(utf8_boundary(&[0xff, b'a', b'b']), 3);
    assert_eq!(utf8_boundary(&[0xff, 0xc3]), 1);
    assert_eq!(utf8_boundary(&[0xff, 0xc3, 0xa9]), 3);
    assert_eq!(utf8_boundary(&[0xe0, 0x80]), 2);

    assert_eq!(utf8_boundary(b"a\xffbbb"), 5);
}

#[tokio::test]
async fn streaming_output_bounds_invalid_bytes_and_keeps_the_full_transcript() {
    let StreamingOutputHarness {
        process,
        stdout_tx,
        exit_tx,
        transcript,
        context,
        rx_event,
        ..
    } = output_harness().await.expect("start output owner");
    let mut receiver = process.output_receiver();
    let mut output = Buffer::<8> {
        pending: Vec::new(),
        emitter: Emitter {
            remaining_deltas: 2,
            session: context.session,
            turn: Arc::clone(&context.step_context.turn),
            call_id: "bounded-output-test".to_string(),
        },
    };

    // The first frame splits 😀; the last allowed frame leaves é incomplete.
    let bytes = b"\xff\xff\xff\xff\xff\xff\xf0\x9f\x98\x80\xff\xff\xff\xc3\xa9";
    for chunk in [bytes.to_vec(), vec![0xfe, 0xfe]] {
        stdout_tx.send(chunk).expect("send raw process bytes");
        output
            .push(receiver.recv().await.expect("receive live output"))
            .await;
    }
    output.finish().await;
    drop(stdout_tx);
    exit_tx.send(0).expect("send exit");

    let mut chunks = Vec::new();
    while let Ok(event) = rx_event.try_recv() {
        let EventMsg::ExecCommandOutputDelta(delta) = event.msg else {
            panic!("expected ExecCommandOutputDelta");
        };
        chunks.push(delta.chunk);
    }
    assert_eq!(
        chunks,
        vec![
            b"\xff\xff\xff\xff\xff\xff".to_vec(),
            b"\xf0\x9f\x98\x80\xff\xff\xff".to_vec(),
        ]
    );

    let mut expected_transcript = bytes.to_vec();
    expected_transcript.extend([0xfe, 0xfe]);
    assert_eq!(
        transcript.lock().await.to_bytes_with_omission_marker(),
        expected_transcript
    );
}
