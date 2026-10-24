//! Original lifecycle signal observation shared by admitted host compositions.

use crate::AgentdError;

#[cfg(unix)]
pub(crate) async fn shutdown_signal() -> Result<(), AgentdError> {
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let mut interrupt = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())?;
    tokio::select! {
        signal = terminate.recv() => signal.ok_or_else(|| {
            AgentdError::Protocol("SIGTERM listener closed before receiving a signal".to_string())
        })?,
        signal = interrupt.recv() => signal.ok_or_else(|| {
            AgentdError::Protocol("SIGINT listener closed before receiving a signal".to_string())
        })?,
    }
    Ok(())
}

#[cfg(not(unix))]
pub(crate) async fn shutdown_signal() -> Result<(), AgentdError> {
    tokio::signal::ctrl_c().await.map_err(Into::into)
}
