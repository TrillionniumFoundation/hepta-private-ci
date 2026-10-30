use super::wait_for_python_repl_ready_via_probe;
use pretty_assertions::assert_eq;
use std::future::Future;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;
use tokio::sync::broadcast;
use tokio::sync::mpsc;

#[tokio::test]
async fn terminal_echo_does_not_satisfy_python_repl_readiness() -> anyhow::Result<()> {
    let (writer, mut commands) = mpsc::channel(1);
    let (output, mut output_rx) = broadcast::channel(4);
    let readiness = wait_for_python_repl_ready_via_probe(
        &writer,
        &mut output_rx,
        /*timeout_ms*/ 5_000,
        "\n",
    );
    tokio::pin!(readiness);
    let mut context = Context::from_waker(Waker::noop());

    assert!(readiness.as_mut().poll(&mut context).is_pending());
    let echoed_command = commands.try_recv()?;
    output.send(echoed_command.clone())?;
    assert!(
        readiness.as_mut().poll(&mut context).is_pending(),
        "terminal echo was accepted before Python executed the probe"
    );

    let executed_output = b"__codex_pty_ready__\r\n".to_vec();
    output.send(executed_output.clone())?;
    let collected = match readiness.as_mut().poll(&mut context) {
        Poll::Ready(result) => result?,
        Poll::Pending => anyhow::bail!("executed probe did not establish readiness"),
    };
    let mut expected = echoed_command;
    expected.extend_from_slice(&executed_output);
    assert_eq!(collected, expected);
    Ok(())
}
