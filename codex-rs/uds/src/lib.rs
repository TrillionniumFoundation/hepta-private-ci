//! Cross-platform async Unix domain socket helpers.

use std::io::Result as IoResult;
use std::path::Path;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;

use tokio::io::AsyncRead;
use tokio::io::AsyncWrite;
use tokio::io::ReadBuf;

/// Creates `socket_dir` if needed and restricts it to the current user where
/// the platform exposes Unix permissions.
pub async fn prepare_private_socket_directory(socket_dir: impl AsRef<Path>) -> IoResult<()> {
    platform::prepare_private_socket_directory(socket_dir.as_ref()).await
}

/// Returns whether `socket_path` points at a stale Unix socket rendezvous path.
///
/// On Unix this checks the file type. On Windows, `uds_windows` represents the
/// rendezvous as a regular path, so existence is the only useful stale-path
/// signal available.
pub async fn is_stale_socket_path(socket_path: impl AsRef<Path>) -> IoResult<bool> {
    platform::is_stale_socket_path(socket_path.as_ref()).await
}

/// Rejects a connected peer whose operating-system user identity differs from
/// the current process. Call this before reading any owner-local control
/// protocol bytes from the stream.
pub fn ensure_current_user_peer(stream: &UnixStream) -> IoResult<()> {
    platform::ensure_current_user_peer(&stream.inner)
}

/// Async Unix domain socket listener.
pub struct UnixListener {
    inner: platform::Listener,
}

impl UnixListener {
    /// Binds a new listener at `socket_path`.
    pub async fn bind(socket_path: impl AsRef<Path>) -> IoResult<Self> {
        platform::bind_listener(socket_path.as_ref())
            .await
            .map(|inner| Self { inner })
    }

    /// Accepts the next incoming stream.
    pub async fn accept(&mut self) -> IoResult<UnixStream> {
        self.inner.accept().await.map(|inner| UnixStream { inner })
    }
}

/// Async Unix domain socket stream.
pub struct UnixStream {
    inner: platform::Stream,
}

impl UnixStream {
    /// Connects to `socket_path`.
    pub async fn connect(socket_path: impl AsRef<Path>) -> IoResult<Self> {
        platform::connect_stream(socket_path.as_ref())
            .await
            .map(|inner| Self { inner })
    }

    /// Fail closed unless the connected peer belongs to this process owner.
    ///
    /// Owner-only socket permissions protect rendezvous by path; this check
    /// additionally binds accepted mutation authority to the kernel-reported
    /// peer identity on Unix.
    pub fn ensure_current_user_peer(&self) -> IoResult<()> {
        platform::ensure_current_user_peer(&self.inner)
    }
}

impl AsyncRead for UnixStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<IoResult<()>> {
        Pin::new(&mut self.get_mut().inner).poll_read(cx, buf)
    }
}

impl AsyncWrite for UnixStream {
    fn poll_write(self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &[u8]) -> Poll<IoResult<usize>> {
        Pin::new(&mut self.get_mut().inner).poll_write(cx, buf)
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(cx)
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(cx)
    }
}

#[cfg(unix)]
mod platform {
    use std::io;
    use std::io::ErrorKind;
    use std::io::Result as IoResult;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::io::AsRawFd;
    use std::path::Path;

    use tokio::fs;
    use tokio::net::UnixListener;
    use tokio::net::UnixStream;

    /// Owner-only access keeps the control socket directory private while
    /// preserving owner traversal and socket path creation.
    const SOCKET_DIR_MODE: u32 = 0o700;
    const SOCKET_DIR_PERMISSION_BITS: u32 = 0o777;

    pub(super) type Stream = UnixStream;

    pub(super) struct Listener(UnixListener);

    pub(super) async fn prepare_private_socket_directory(socket_dir: &Path) -> IoResult<()> {
        let mut dir_builder = fs::DirBuilder::new();
        dir_builder.mode(SOCKET_DIR_MODE);
        match dir_builder.create(socket_dir).await {
            Ok(()) => return Ok(()),
            Err(err) if err.kind() == ErrorKind::AlreadyExists => {}
            Err(err) => return Err(err),
        }

        let metadata = fs::symlink_metadata(socket_dir).await?;
        if !metadata.is_dir() {
            return Err(io::Error::new(
                ErrorKind::AlreadyExists,
                format!(
                    "socket directory path exists and is not a directory: {}",
                    socket_dir.display()
                ),
            ));
        }

        let permissions = metadata.permissions();
        // The SSH-over-UDS control socket is reachable by path, so the
        // rendezvous directory must be owner-traversable while denying
        // group/other access; exact 0700 fixes insecure modes and unusable
        // owner-only modes like 0600.
        if permissions.mode() & SOCKET_DIR_PERMISSION_BITS != SOCKET_DIR_MODE {
            fs::set_permissions(socket_dir, std::fs::Permissions::from_mode(SOCKET_DIR_MODE))
                .await?;
        }

        Ok(())
    }

    // sockaddr_un::sun_path reserves one trailing NUL byte. Linux/Android
    // expose 108 bytes; Apple and BSD targets expose 104. Reject before the
    // syscall so callers see the real contract violation instead of a platform-
    // specific EINVAL/EPERM/ENOENT translation.
    #[cfg(any(target_os = "linux", target_os = "android"))]
    const MAX_PATHNAME_SOCKET_BYTES: usize = 107;
    #[cfg(not(any(target_os = "linux", target_os = "android")))]
    const MAX_PATHNAME_SOCKET_BYTES: usize = 103;

    fn validate_socket_path(socket_path: &Path) -> IoResult<()> {
        let raw = socket_path.as_os_str().as_bytes();
        let length = raw.len();
        if length > MAX_PATHNAME_SOCKET_BYTES {
            Err(io::Error::new(
                ErrorKind::InvalidInput,
                format!(
                    "Unix socket path is {length} bytes; platform maximum is {MAX_PATHNAME_SOCKET_BYTES}: {}",
                    socket_path.display()
                ),
            ))
        } else if raw.contains(&0) {
            Err(io::Error::new(
                ErrorKind::InvalidInput,
                "Unix socket path contains a NUL byte",
            ))
        } else {
            Ok(())
        }
    }

    pub(super) async fn bind_listener(socket_path: &Path) -> IoResult<Listener> {
        validate_socket_path(socket_path)?;
        UnixListener::bind(socket_path).map(Listener)
    }

    impl Listener {
        pub(super) async fn accept(&mut self) -> IoResult<Stream> {
            self.0.accept().await.map(|(stream, _addr)| stream)
        }
    }

    pub(super) async fn connect_stream(socket_path: &Path) -> IoResult<Stream> {
        validate_socket_path(socket_path)?;
        UnixStream::connect(socket_path).await
    }

    #[cfg(any(target_os = "linux", target_os = "android"))]
    pub(super) fn ensure_current_user_peer(stream: &Stream) -> IoResult<()> {
        let mut credentials = libc::ucred {
            pid: 0,
            uid: 0,
            gid: 0,
        };
        let mut credentials_len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
        let result = unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                std::ptr::addr_of_mut!(credentials).cast(),
                &mut credentials_len,
            )
        };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        ensure_peer_uid(credentials.uid)
    }

    #[cfg(any(
        target_os = "macos",
        target_os = "ios",
        target_os = "freebsd",
        target_os = "openbsd",
        target_os = "netbsd",
        target_os = "dragonfly"
    ))]
    pub(super) fn ensure_current_user_peer(stream: &Stream) -> IoResult<()> {
        let mut peer_uid: libc::uid_t = 0;
        let mut peer_gid: libc::gid_t = 0;
        let result = unsafe { libc::getpeereid(stream.as_raw_fd(), &mut peer_uid, &mut peer_gid) };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        ensure_peer_uid(peer_uid)
    }

    #[cfg(not(any(
        target_os = "linux",
        target_os = "android",
        target_os = "macos",
        target_os = "ios",
        target_os = "freebsd",
        target_os = "openbsd",
        target_os = "netbsd",
        target_os = "dragonfly"
    )))]
    pub(super) fn ensure_current_user_peer(_stream: &Stream) -> IoResult<()> {
        Err(io::Error::new(
            ErrorKind::Unsupported,
            "peer user identity is unavailable on this platform",
        ))
    }

    fn ensure_peer_uid(peer_uid: libc::uid_t) -> IoResult<()> {
        if peer_uid == unsafe { libc::getuid() } {
            Ok(())
        } else {
            Err(io::Error::new(
                ErrorKind::PermissionDenied,
                "Unix socket peer is not owned by the current user",
            ))
        }
    }

    pub(super) async fn is_stale_socket_path(socket_path: &Path) -> IoResult<bool> {
        Ok(fs::symlink_metadata(socket_path)
            .await?
            .file_type()
            .is_socket())
    }

    #[cfg(test)]
    mod tests {
        use std::io::ErrorKind;

        use super::MAX_PATHNAME_SOCKET_BYTES;
        use super::ensure_peer_uid;
        use super::validate_socket_path;
        use std::path::Path;

        #[test]
        fn pathname_socket_limit_rejects_before_bind_or_connect() {
            let exact = format!("/{}", "s".repeat(MAX_PATHNAME_SOCKET_BYTES - 1));
            validate_socket_path(Path::new(&exact)).expect("maximum path must fit");

            let oversized = format!("/{}", "s".repeat(MAX_PATHNAME_SOCKET_BYTES));
            let error = validate_socket_path(Path::new(&oversized))
                .expect_err("overlong socket path must fail before the syscall");
            assert_eq!(error.kind(), ErrorKind::InvalidInput);
            assert!(error.to_string().contains("platform maximum"));
        }

        #[test]
        fn peer_uid_gate_accepts_only_the_process_owner() {
            let owner = unsafe { libc::getuid() };
            ensure_peer_uid(owner).expect("the process owner must pass the UDS peer gate");

            let non_owner = if owner == libc::uid_t::MAX {
                owner - 1
            } else {
                owner + 1
            };
            let error = ensure_peer_uid(non_owner)
                .expect_err("a different UID must fail closed before reading the request");
            assert_eq!(error.kind(), ErrorKind::PermissionDenied);
        }
    }
}

#[cfg(windows)]
mod platform {
    use std::io;
    use std::io::Result as IoResult;
    use std::net::Shutdown;
    use std::ops::Deref;
    use std::os::windows::io::AsRawSocket;
    use std::os::windows::io::AsSocket;
    use std::os::windows::io::BorrowedSocket;
    use std::path::Path;
    use std::pin::Pin;
    use std::task::Context;
    use std::task::Poll;
    use std::task::ready;

    use async_io::Async;
    use tokio::io::AsyncRead;
    use tokio::io::AsyncWrite;
    use tokio::io::ReadBuf;
    use tokio::task;
    use tokio_util::compat::Compat;
    use tokio_util::compat::FuturesAsyncReadCompatExt;

    pub(super) struct Stream(Compat<Async<WindowsUnixStream>>);

    pub(super) async fn prepare_private_socket_directory(socket_dir: &Path) -> IoResult<()> {
        tokio::fs::create_dir_all(socket_dir).await
    }

    pub(super) struct Listener(Async<WindowsUnixListener>);

    pub(super) async fn bind_listener(socket_path: &Path) -> IoResult<Listener> {
        let socket_path = socket_path.to_path_buf();
        let listener =
            spawn_blocking_io(move || uds_windows::UnixListener::bind(socket_path)).await?;
        Async::new(WindowsUnixListener::from(listener)).map(Listener)
    }

    impl Listener {
        pub(super) async fn accept(&mut self) -> IoResult<Stream> {
            let (stream, _addr) = self.0.read_with(|listener| listener.accept()).await?;
            Async::new(WindowsUnixStream::from(stream))
                .map(FuturesAsyncReadCompatExt::compat)
                .map(Stream)
        }
    }

    pub(super) async fn connect_stream(socket_path: &Path) -> IoResult<Stream> {
        let socket_path = socket_path.to_path_buf();
        let stream =
            spawn_blocking_io(move || uds_windows::UnixStream::connect(socket_path)).await?;
        Async::new(WindowsUnixStream::from(stream))
            .map(FuturesAsyncReadCompatExt::compat)
            .map(Stream)
    }

    pub(super) fn ensure_current_user_peer(_stream: &Stream) -> IoResult<()> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "peer user identity is unavailable on this platform",
        ))
    }

    pub(super) async fn is_stale_socket_path(socket_path: &Path) -> IoResult<bool> {
        tokio::fs::try_exists(socket_path).await
    }

    async fn spawn_blocking_io<T>(
        operation: impl FnOnce() -> IoResult<T> + Send + 'static,
    ) -> IoResult<T>
    where
        T: Send + 'static,
    {
        task::spawn_blocking(operation)
            .await
            .map_err(|err| io::Error::other(format!("blocking socket task failed: {err}")))?
    }

    pub(super) struct WindowsUnixListener(uds_windows::UnixListener);

    impl From<uds_windows::UnixListener> for WindowsUnixListener {
        fn from(listener: uds_windows::UnixListener) -> Self {
            Self(listener)
        }
    }

    impl Deref for WindowsUnixListener {
        type Target = uds_windows::UnixListener;

        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl AsSocket for WindowsUnixListener {
        fn as_socket(&self) -> BorrowedSocket<'_> {
            unsafe { BorrowedSocket::borrow_raw(self.as_raw_socket()) }
        }
    }

    pub(super) struct WindowsUnixStream(uds_windows::UnixStream);

    impl From<uds_windows::UnixStream> for WindowsUnixStream {
        fn from(stream: uds_windows::UnixStream) -> Self {
            Self(stream)
        }
    }

    impl Deref for WindowsUnixStream {
        type Target = uds_windows::UnixStream;

        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl AsSocket for WindowsUnixStream {
        fn as_socket(&self) -> BorrowedSocket<'_> {
            unsafe { BorrowedSocket::borrow_raw(self.as_raw_socket()) }
        }
    }

    impl io::Read for WindowsUnixStream {
        fn read(&mut self, buf: &mut [u8]) -> IoResult<usize> {
            io::Read::read(&mut self.0, buf)
        }
    }

    impl io::Write for WindowsUnixStream {
        fn write(&mut self, buf: &[u8]) -> IoResult<usize> {
            io::Write::write(&mut self.0, buf)
        }

        fn flush(&mut self) -> IoResult<()> {
            io::Write::flush(&mut self.0)
        }
    }

    impl AsyncRead for Stream {
        fn poll_read(
            self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            buf: &mut ReadBuf<'_>,
        ) -> Poll<IoResult<()>> {
            Pin::new(&mut self.get_mut().0).poll_read(cx, buf)
        }
    }

    impl AsyncWrite for Stream {
        fn poll_write(
            self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            buf: &[u8],
        ) -> Poll<IoResult<usize>> {
            Pin::new(&mut self.get_mut().0).poll_write(cx, buf)
        }

        fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
            Pin::new(&mut self.get_mut().0).poll_flush(cx)
        }

        fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
            let stream = &mut self.get_mut().0;
            ready!(Pin::new(&mut *stream).poll_flush(cx))?;
            // `Compat<Async<_>>` maps shutdown to `poll_close()`, which only
            // flushes for `async_io::Async`; call the socket shutdown directly.
            stream.get_ref().get_ref().shutdown(Shutdown::Write)?;
            Poll::Ready(Ok(()))
        }
    }

    unsafe impl async_io::IoSafe for WindowsUnixListener {}
    unsafe impl async_io::IoSafe for WindowsUnixStream {}
}

#[cfg(test)]
mod lib_tests;
