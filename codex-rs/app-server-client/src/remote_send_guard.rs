//! Optional final-entry fencing in the existing remote transport writer.
//!
//! A rejected guard is not a durable no-effect receipt. Callers must continue
//! reconciliation after an ambiguous request result; this API never retries.

use std::future::Future;
use std::future::poll_fn;
use std::io;
use std::pin::Pin;

use futures::FutureExt;
use futures::Sink;
use futures::SinkExt;
use tokio::sync::oneshot;
use tokio::time::Instant;

/// A one-shot authorization check performed after queue and sink readiness.
/// Preparation may await fresh owner observations. Its returned entry closure
/// must check current authority synchronously; no await separates it from
/// `start_send`. The returned value is held through flush (for authority leases).
/// Preparation must use independent owner channels: awaiting another request on
/// this same client would block behind the command currently being guarded.
pub struct RemoteRequestSendGuard {
    deadline: Instant,
    cancelled: Pin<Box<dyn Future<Output = ()> + Send>>,
    prepare: Pin<Box<dyn Future<Output = io::Result<Entry>> + Send>>,
}

type Entry = Box<dyn FnOnce() -> io::Result<Box<dyn Send>> + Send>;

impl RemoteRequestSendGuard {
    pub fn new<C, P, E, L>(deadline: Instant, cancelled: C, prepare: P) -> Self
    where
        C: Future<Output = ()> + Send + 'static,
        P: Future<Output = io::Result<E>> + Send + 'static,
        E: FnOnce() -> io::Result<L> + Send + 'static,
        L: Send + 'static,
    {
        Self {
            deadline,
            cancelled: Box::pin(cancelled),
            prepare: Box::pin(async move {
                let enter = prepare.await?;
                Ok(
                    Box::new(move || enter().map(|lease| Box::new(lease) as Box<dyn Send>))
                        as Entry,
                )
            }),
        }
    }
}

pub(crate) async fn send_guarded<S, M, R>(
    sink: &mut S,
    message: M,
    response: &mut oneshot::Sender<R>,
    guard: RemoteRequestSendGuard,
) -> io::Result<()>
where
    S: Sink<M> + Unpin,
    S::Error: std::error::Error + Send + Sync + 'static,
{
    let RemoteRequestSendGuard {
        deadline,
        mut cancelled,
        prepare,
    } = guard;
    let enter = tokio::select! {
        biased;
        _ = response.closed() => return Err(io::Error::new(io::ErrorKind::Interrupted, "guarded request abandoned before send")),
        _ = &mut cancelled => return Err(io::Error::new(io::ErrorKind::Interrupted, "guarded request cancelled before send")),
        _ = tokio::time::sleep_until(deadline) => return Err(io::Error::new(io::ErrorKind::TimedOut, "guarded request deadline elapsed before send")),
        result = async {
            poll_fn(|cx| Pin::new(&mut *sink).poll_ready(cx)).await.map_err(io::Error::other)?;
            prepare.await
        } => result?,
    };
    // Recheck after preparation, including a synchronous callback that consumes
    // time. No executor yield is allowed between this check and start_send.
    if response.is_closed() || cancelled.as_mut().now_or_never().is_some() {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "guarded request cancelled or abandoned before entry",
        ));
    }
    if Instant::now() >= deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "guarded request deadline elapsed before entry",
        ));
    }
    let _lease = enter()?;
    if response.is_closed() || cancelled.as_mut().now_or_never().is_some() {
        return Err(io::Error::new(
            io::ErrorKind::Interrupted,
            "guarded request cancelled or abandoned during entry",
        ));
    }
    if Instant::now() >= deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "guarded request deadline elapsed during entry",
        ));
    }
    Pin::new(&mut *sink)
        .start_send(message)
        .map_err(io::Error::other)?;
    // After start_send any failure is ambiguous. Never reuse a pre-effect proof.
    tokio::select! {
        biased;
        _ = response.closed() => Err(io::Error::new(io::ErrorKind::Interrupted, "guarded request abandoned after start_send; reconcile only")),
        _ = &mut cancelled => Err(io::Error::new(io::ErrorKind::Interrupted, "guarded request cancelled after start_send; reconcile only")),
        _ = tokio::time::sleep_until(deadline) => Err(io::Error::new(io::ErrorKind::TimedOut, "guarded request deadline elapsed after start_send; reconcile only")),
        result = sink.flush() => result.map_err(io::Error::other),
    }
}

#[cfg(test)]
#[path = "remote_send_guard_tests.rs"]
mod tests;
