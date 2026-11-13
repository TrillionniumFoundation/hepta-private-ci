//! Server-owned signal subscriptions outlive any one main-loop receive future.
use std::io;

use crate::ShutdownSignal;

pub(super) struct ShutdownSignals {
    #[cfg(unix)]
    interrupt: tokio::signal::unix::Signal,
    #[cfg(unix)]
    terminate: tokio::signal::unix::Signal,
    #[cfg(unix)]
    hangup: tokio::signal::unix::Signal,
}

impl ShutdownSignals {
    pub(super) fn register() -> io::Result<Self> {
        #[cfg(unix)]
        {
            use tokio::signal::unix::SignalKind;
            use tokio::signal::unix::signal;

            Ok(Self {
                interrupt: signal(SignalKind::interrupt())?,
                terminate: signal(SignalKind::terminate())?,
                hangup: signal(SignalKind::hangup())?,
            })
        }
        #[cfg(not(unix))]
        {
            Ok(Self {})
        }
    }

    pub(super) async fn recv(&mut self) -> io::Result<ShutdownSignal> {
        #[cfg(unix)]
        {
            let (received, signal) = tokio::select! {
                received = self.interrupt.recv() => (received, ShutdownSignal::Forceable),
                received = self.terminate.recv() => (received, ShutdownSignal::Forceable),
                received = self.hangup.recv() => (received, ShutdownSignal::GracefulOnly),
            };
            received
                .map(|()| signal)
                .ok_or_else(|| io::Error::other("shutdown signal receiver closed"))
        }
        #[cfg(not(unix))]
        {
            tokio::signal::ctrl_c()
                .await
                .map(|()| ShutdownSignal::Forceable)
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "shutdown_signals_tests.rs"]
mod tests;
