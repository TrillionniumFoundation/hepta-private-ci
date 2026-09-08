#!/usr/bin/env python3
"""Apply the exact Agentd/UDS gap-closure patch to a pinned checkout."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one occurrence of {old!r}, found {count}"
        )
    file.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    replace_once(
        "codex-rs/hepta-agentd/src/app_runtime.rs",
        '''        contextual_io_error(
            "run Codex App Server unix socket transport",
            &identity.app_server_socket,
            error,
        )''',
        '''        contextual_io_error(
            /* operation */ "run Codex App Server unix socket transport",
            /* path */ &identity.app_server_socket,
            /* source */ error,
        )''',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/control.rs",
        '''            return Err(io_context(
                "probe existing agentd control socket",
                socket_path,
                error,
            ));''',
        '''            return Err(io_context(
                /* operation */ "probe existing agentd control socket",
                /* path */ socket_path,
                /* source */ error,
            ));''',
    )
    replace_once(
        "codex-rs/hepta-agentd/tests/support/fleet.rs",
        '''        let temp = tempfile::tempdir()?;
        let root = temp.path().canonicalize()?;''',
        '''        // macOS limits pathname-based AF_UNIX endpoints to 103 bytes. Its
        // hosted-runner TMPDIR is intentionally deep, so use a short private root
        // for process qualification rather than hiding a bind failure as EPERM.
        let temp = if cfg!(target_os = "macos") {
            tempfile::Builder::new().prefix("hpa").tempdir_in("/tmp")?
        } else {
            tempfile::tempdir()?
        };
        let root = temp.path().canonicalize()?;''',
    )

    uds = Path("codex-rs/uds/src/lib.rs")
    text = uds.read_text(encoding="utf-8")
    import_line = "    use std::os::unix::fs::PermissionsExt;\n"
    if text.count(import_line) != 1:
        raise SystemExit("UDS OsStrExt import marker drifted")
    text = text.replace(
        import_line,
        "    use std::os::unix::ffi::OsStrExt;\n" + import_line,
        1,
    )

    bind_marker = '''    pub(super) async fn bind_listener(socket_path: &Path) -> IoResult<Listener> {
        UnixListener::bind(socket_path).map(Listener)
    }
'''
    if text.count(bind_marker) != 1:
        raise SystemExit("UDS bind marker drifted")
    text = text.replace(
        bind_marker,
        '''    // sockaddr_un::sun_path reserves one trailing NUL byte. Linux/Android
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
''',
        1,
    )

    connect_marker = '''    pub(super) async fn connect_stream(socket_path: &Path) -> IoResult<Stream> {
        UnixStream::connect(socket_path).await
    }
'''
    if text.count(connect_marker) != 1:
        raise SystemExit("UDS connect marker drifted")
    text = text.replace(
        connect_marker,
        '''    pub(super) async fn connect_stream(socket_path: &Path) -> IoResult<Stream> {
        validate_socket_path(socket_path)?;
        UnixStream::connect(socket_path).await
    }
''',
        1,
    )

    test_import = "        use super::ensure_peer_uid;\n"
    if text.count(test_import) != 1:
        raise SystemExit("UDS test import marker drifted")
    text = text.replace(
        test_import,
        '''        use super::MAX_PATHNAME_SOCKET_BYTES;
        use super::ensure_peer_uid;
        use super::validate_socket_path;
        use std::path::Path;
''',
        1,
    )

    test_marker = '''        #[test]
        fn peer_uid_gate_accepts_only_the_process_owner() {
'''
    if text.count(test_marker) != 1:
        raise SystemExit("UDS test insertion marker drifted")
    text = text.replace(
        test_marker,
        '''        #[test]
        fn pathname_socket_limit_rejects_before_bind_or_connect() {
            let exact = format!("/{}", "s".repeat(MAX_PATHNAME_SOCKET_BYTES - 1));
            validate_socket_path(Path::new(&exact)).expect("maximum path must fit");

            let oversized = format!("/{}", "s".repeat(MAX_PATHNAME_SOCKET_BYTES));
            let error = validate_socket_path(Path::new(&oversized))
                .expect_err("overlong socket path must fail before the syscall");
            assert_eq!(error.kind(), ErrorKind::InvalidInput);
            assert!(error.to_string().contains("platform maximum"));
        }

''' + test_marker,
        1,
    )
    uds.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
