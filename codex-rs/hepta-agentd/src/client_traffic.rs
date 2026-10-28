//! Per-client observed transport costs, including partial reads and writes.

use std::pin::Pin;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;

use serde::Serialize;
use tokio::io::AsyncRead;
use tokio::io::ReadBuf;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AgentdTrafficSnapshotV1 {
    pub rpc_attempts: u64,
    pub transmitted_bytes: u64,
    pub received_bytes: u64,
}

#[derive(Default)]
pub(super) struct ClientTraffic {
    pub attempts: AtomicU64,
    pub transmitted: AtomicU64,
    pub received: AtomicU64,
}

impl ClientTraffic {
    pub fn snapshot(&self) -> AgentdTrafficSnapshotV1 {
        AgentdTrafficSnapshotV1 {
            rpc_attempts: self.attempts.load(Ordering::Relaxed),
            transmitted_bytes: self.transmitted.load(Ordering::Relaxed),
            received_bytes: self.received.load(Ordering::Relaxed),
        }
    }
}

pub(super) struct MeteredRead<'a, R> {
    pub reader: R,
    pub received: &'a AtomicU64,
}

impl<R: AsyncRead + Unpin> AsyncRead for MeteredRead<'_, R> {
    fn poll_read(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        let this = self.get_mut();
        let before = buffer.filled().len();
        let result = Pin::new(&mut this.reader).poll_read(context, buffer);
        this.received
            .fetch_add((buffer.filled().len() - before) as u64, Ordering::Relaxed);
        result
    }
}
