//! Authenticated owner-local control transports. General AF_UNIX remains separate.

use std::io;
use std::path::Path;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;

use tokio::io::AsyncRead;
use tokio::io::AsyncWrite;
use tokio::io::ReadBuf;

#[cfg(windows)]
#[path = "owner_local_windows.rs"]
mod platform;

#[cfg(unix)]
mod platform {
    use super::*;

    pub(super) type Listener = crate::UnixListener;
    pub(super) type Incoming = crate::UnixStream;

    pub(super) async fn authenticate(stream: Incoming) -> io::Result<OwnerLocalStream> {
        stream.ensure_current_user_peer()?;
        Ok(OwnerLocalStream {
            inner: Box::new(stream),
        })
    }

    pub(super) async fn connect(path: &Path) -> io::Result<OwnerLocalStream> {
        authenticate(crate::UnixStream::connect(path).await?).await
    }
}

/// A same-user control listener; Unix retains its existing UDS wire protocol.
///
/// Unix callers remain responsible for the private rendezvous directory and
/// socket lifetime. Windows uses an atomically protected, local named pipe with
/// a first-instance claim; filesystem socket paths are only endpoint identifiers.
pub struct OwnerLocalListener {
    inner: platform::Listener,
}

impl OwnerLocalListener {
    pub async fn bind(path: impl AsRef<Path>) -> io::Result<Self> {
        Ok(Self {
            inner: platform::Listener::bind(path.as_ref()).await?,
        })
    }

    /// Accept without reading application bytes or consuming a handshake slot.
    /// The caller should apply its connection limit and absolute I/O deadline
    /// before authenticating the returned pending stream.
    pub async fn accept(&mut self) -> io::Result<OwnerLocalIncoming> {
        Ok(OwnerLocalIncoming {
            inner: self.inner.accept().await?,
        })
    }
}

/// A pending connection that cannot read or write application data.
pub struct OwnerLocalIncoming {
    inner: platform::Incoming,
}

impl OwnerLocalIncoming {
    /// Authenticate before exposing application I/O. Windows exchanges only a
    /// fixed transport preface, verifies the connected client's token SID, and
    /// restores the thread token before its next asynchronous operation.
    pub async fn authenticate(self) -> io::Result<OwnerLocalStream> {
        platform::authenticate(self.inner).await
    }
}

/// I/O capabilities retained privately until transport authentication completes.
trait LocalIo: AsyncRead + AsyncWrite + Unpin + Send {}

impl<T: AsyncRead + AsyncWrite + Unpin + Send> LocalIo for T {}

/// An authenticated same-user local stream.
///
/// This authenticates the OS user boundary, not a particular executable under
/// that same user. Application identity, generation and fence checks still apply.
pub struct OwnerLocalStream {
    inner: Box<dyn LocalIo>,
}

impl OwnerLocalStream {
    /// Connect and authenticate the server before exposing application I/O.
    /// On Windows both the actual pipe handle's owner/DACL and the fixed
    /// transport acknowledgement are checked within a two-second deadline.
    pub async fn connect(path: impl AsRef<Path>) -> io::Result<Self> {
        platform::connect(path.as_ref()).await
    }
}

impl AsyncRead for OwnerLocalStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut *self.get_mut().inner).poll_read(cx, buf)
    }
}

impl AsyncWrite for OwnerLocalStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut *self.get_mut().inner).poll_write(cx, buf)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut *self.get_mut().inner).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut *self.get_mut().inner).poll_shutdown(cx)
    }
}

#[cfg(test)]
#[path = "owner_local_tests.rs"]
mod tests;
