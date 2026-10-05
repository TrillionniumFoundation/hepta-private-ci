use super::*;
use std::fs;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Result<Self> {
        let base = std::env::temp_dir().canonicalize()?;
        for _ in 0..100 {
            let path = base.join(format!(
                "hepta-ui-bundle-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            match fs::create_dir(&path) {
                Ok(()) => return Ok(Self(path)),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error.into()),
            }
        }
        anyhow::bail!("cannot create isolated fixture")
    }

    fn bundle(&self) -> Result<UiBundleOptions> {
        let mut files = serde_json::Map::new();
        for (name, bytes) in [
            ("index.html", b"<canvas></canvas>".as_slice()),
            ("bootstrap.js", b"// fixture".as_slice()),
            ("input-platform.css", b"canvas{}".as_slice()),
            ("app.wasm", b"\0asm\x01\0\0\0".as_slice()),
        ] {
            fs::write(self.0.join(name), bytes)?;
            files.insert(
                name.to_owned(),
                serde_json::json!({"bytes":bytes.len(),"sha256":digest(bytes)}),
            );
        }
        self.manifest(&serde_json::json!({
            "schema":"hepta.robrix-ui.build.v1", "browserRuntime":"rust-makepad-wasm",
            "fixtures":false,"threads":false,"automaticCrashUpload":false,
            "sourceIdentity":{"sha256":"a".repeat(64)},"files":files
        }))
    }

    fn manifest(&self, value: &serde_json::Value) -> Result<UiBundleOptions> {
        let bytes = serde_json::to_vec(value)?;
        fs::write(self.0.join("build-manifest.json"), &bytes)?;
        Ok(UiBundleOptions {
            directory: self.0.clone(),
            manifest_sha256: digest(&bytes),
        })
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[cfg(unix)]
#[test]
fn verified_snapshot_survives_asset_replacement_without_copying_bodies() -> Result<()> {
    let fixture = Fixture::new()?;
    let options = fixture.bundle()?;
    let bundle = UiBundle::load(&options)?;
    let first = bundle.response("/").context("entry")?;
    fs::write(fixture.0.join("replacement"), "changed")?;
    fs::rename(fixture.0.join("replacement"), fixture.0.join("index.html"))?;
    let second = bundle.response("/index.html").context("entry")?;
    assert!(Arc::ptr_eq(&first.body, &second.body));
    assert_eq!(&*second.body, b"<canvas></canvas>");
    assert!(UiBundle::load(&options).is_err());
    assert!(std::str::from_utf8(&first.headers)?.contains("Content-Security-Policy:"));
    assert!(bundle.response("/build-manifest.json").is_some());
    Ok(())
}

#[cfg(unix)]
#[test]
fn malformed_requests_never_escape_the_selected_asset_map() -> Result<()> {
    let fixture = Fixture::new()?;
    let bundle = UiBundle::load(&fixture.bundle()?)?;
    for target in [
        "/../index.html",
        "/%2e%2e/index.html",
        "/x%2findex.html",
        "//index.html",
        "/x\\index.html",
        "/api/hepta/runtime",
        "/healthz",
        "/unlisted.js",
    ] {
        assert!(bundle.response(target).is_none(), "{target}");
    }
    for request in [
        b"POST / HTTP/1.1\r\n\r\n".as_slice(),
        b"GET / BAD\r\n\r\n",
        b"GET / HTTP/1.1 extra\r\n\r\n",
    ] {
        assert!(crate::ui_response(request, &bundle).is_none());
    }
    assert!(crate::ui_response(b"GET / HTTP/1.1\r\n\r\n", &bundle).is_some());
    Ok(())
}

#[cfg(unix)]
#[test]
fn manifest_selection_and_resource_failures_are_closed() -> Result<()> {
    let fixture = Fixture::new()?;
    let options = fixture.bundle()?;
    let mut wrong = options;
    wrong.manifest_sha256 = "0".repeat(64);
    assert!(UiBundle::load(&wrong).is_err());
    let original: serde_json::Value =
        serde_json::from_slice(&fs::read(fixture.0.join("build-manifest.json"))?)?;
    for field in ["fixtures", "threads", "automaticCrashUpload"] {
        let mut changed = original.clone();
        changed[field] = true.into();
        assert!(UiBundle::load(&fixture.manifest(&changed)?).is_err());
    }
    for path in ["../escape.js", "api/hepta/runtime", "build-manifest.json"] {
        let mut changed = original.clone();
        changed["files"][path] = serde_json::json!({"bytes":0,"sha256":digest(b"")});
        assert!(UiBundle::load(&fixture.manifest(&changed)?).is_err());
    }
    let options = fixture.manifest(&original)?;
    fs::remove_file(fixture.0.join("bootstrap.js"))?;
    assert!(UiBundle::load(&options).is_err());
    fs::write(fixture.0.join("bootstrap.js"), "too many fixture bytes")?;
    assert!(UiBundle::load(&options).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn anchored_reader_rejects_symlink_ancestors_and_final_files() -> Result<()> {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new()?;
    fs::create_dir(fixture.0.join("real"))?;
    fs::write(fixture.0.join("real/file.txt"), "safe")?;
    symlink("real", fixture.0.join("link"))?;
    let directory = reader::Directory::open(&fixture.0)?;
    assert!(reader::Directory::open(&fixture.0.join("link")).is_err());
    assert!(directory.read("link/file.txt", 4).is_err());
    symlink("real/file.txt", fixture.0.join("file.txt"))?;
    assert!(directory.read("file.txt", 4).is_err());
    assert_eq!(directory.read("real/file.txt", 4)?, b"safe");
    Ok(())
}

#[cfg(unix)]
#[test]
fn pinned_directory_survives_path_rename_and_replacement() -> Result<()> {
    let fixture = Fixture::new()?;
    let original = fixture.0.join("bundle");
    fs::create_dir(&original)?;
    fs::write(original.join("data.txt"), "original")?;
    let directory = reader::Directory::open(&original)?;
    fs::rename(&original, fixture.0.join("moved"))?;
    fs::create_dir(&original)?;
    fs::write(original.join("data.txt"), "replacement")?;
    assert_eq!(directory.read("data.txt", 32)?, b"original");
    Ok(())
}

#[cfg(unix)]
#[test]
fn nonregular_and_oversize_resources_fail_before_unbounded_read() -> Result<()> {
    let fixture = Fixture::new()?;
    fs::write(fixture.0.join("large.txt"), b"12345")?;
    let directory = reader::Directory::open(&fixture.0)?;
    assert!(directory.read("large.txt", 4).is_err());
    assert!(directory.read("large.txt", 0).is_err());
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        fixture.0.join("pipe.txt"),
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )?;
    assert!(directory.read("pipe.txt", 16).is_err());
    assert!(
        reader::Directory::open(Path::new("/dev"))?
            .read("null", 16)
            .is_err()
    );
    Ok(())
}

#[test]
fn bundle_arguments_are_paired_without_changing_api_only_startup() -> Result<()> {
    let root =
        codex_hepta_paths::HeptaStateRoot::parse(std::env::temp_dir().join("hepta-ui-args"))?;
    assert!(
        crate::NativeGatewayOptions::from_args(&[], root.clone())?
            .ui_bundle
            .is_none()
    );
    assert!(
        crate::NativeGatewayOptions::from_args(
            &["--ui-bundle".to_owned(), "/bundle".to_owned()],
            root.clone()
        )
        .is_err()
    );
    assert!(
        crate::NativeGatewayOptions::from_args(
            &["--ui-manifest-sha256".to_owned(), "a".repeat(64)],
            root
        )
        .is_err()
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn manifest_count_aggregate_and_entry_limits_reject_before_asset_reads() -> Result<()> {
    let fixture = Fixture::new()?;
    fixture.bundle()?;
    let original: serde_json::Value =
        serde_json::from_slice(&fs::read(fixture.0.join("build-manifest.json"))?)?;
    let mut count = original.clone();
    for index in 0..MAX_ASSETS {
        count["files"][format!("extra-{index}.js")] =
            serde_json::json!({"bytes":0,"sha256":digest(b"")});
    }
    let error = UiBundle::load(&fixture.manifest(&count)?)
        .err()
        .context("must reject count")?;
    assert!(error.to_string().contains("count exceeds"));
    let mut aggregate = original.clone();
    for index in 0..3 {
        aggregate["files"][format!("large-{index}.js")] =
            serde_json::json!({"bytes":MAX_ASSET_BYTES,"sha256":digest(b"")});
    }
    let error = UiBundle::load(&fixture.manifest(&aggregate)?)
        .err()
        .context("must reject aggregate")?;
    assert!(error.to_string().contains("memory bound"));
    let mut entry = original;
    entry["files"]
        .as_object_mut()
        .context("fixture files")?
        .remove("index.html");
    let error = UiBundle::load(&fixture.manifest(&entry)?)
        .err()
        .context("must reject entry")?;
    assert!(error.to_string().contains("missing required entry"));
    let oversized = vec![b' '; MAX_MANIFEST_BYTES + 1];
    fs::write(fixture.0.join("build-manifest.json"), &oversized)?;
    let options = UiBundleOptions {
        directory: fixture.0.clone(),
        manifest_sha256: digest(&oversized),
    };
    let error = UiBundle::load(&options)
        .err()
        .context("must reject oversized manifest")?;
    assert!(error.to_string().contains("byte bound"));
    Ok(())
}

#[cfg(unix)]
#[derive(Debug)]
struct SocketAdapter;
#[cfg(unix)]
impl codex_hepta_runtime::RuntimeStateAdapter for SocketAdapter {
    fn status(&self) -> codex_hepta_runtime::RuntimeStateStatus {
        codex_hepta_runtime::RuntimeStateStatus {
            adapter: "ui-socket-fixture",
            schema_version: 5,
            outcome_generation: 1,
            preference_generation: 2,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 3,
            integrity_binding_present: true,
            integrity_verification: "fixture-only",
            open_mode: "read-only-test",
        }
    }
}

#[cfg(unix)]
async fn exchange(
    ui: Option<Arc<UiBundle>>,
    packet: impl FnOnce(std::net::SocketAddr) -> String,
) -> Result<Vec<u8>> {
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let root = codex_hepta_paths::HeptaStateRoot::parse(
        std::env::temp_dir().join("hepta-ui-socket-fixture"),
    )?;
    let runtime = Arc::new(codex_hepta_runtime::HeptaRuntime::from_adapter(
        root,
        Arc::new(SocketAdapter),
    ));
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await?;
        crate::serve_connection(
            stream,
            Some(runtime),
            ui,
            crate::OwnerStatusProvider::default(),
        )
        .await
    });
    let mut client = tokio::net::TcpStream::connect(address).await?;
    client.write_all(packet(address).as_bytes()).await?;
    let mut response = Vec::new();
    tokio::time::timeout(crate::RESPONSE_TIMEOUT, client.read_to_end(&mut response)).await??;
    server.await??;
    Ok(response)
}

#[cfg(unix)]
fn http_parts(response: &[u8]) -> Result<(&str, &[u8])> {
    let offset = response
        .windows(4)
        .position(|bytes| bytes == b"\r\n\r\n")
        .context("HTTP headers")?
        + 4;
    let headers = std::str::from_utf8(&response[..offset])?;
    let length: usize = headers
        .lines()
        .find_map(|line| line.strip_prefix("Content-Length: "))
        .context("HTTP length")?
        .parse()?;
    assert_eq!(response[offset..].len(), length);
    Ok((headers, &response[offset..]))
}

#[cfg(unix)]
#[tokio::test]
async fn real_ui_socket_serves_selected_bytes_and_preserves_read_only_apis() -> Result<()> {
    let fixture = Fixture::new()?;
    let ui = Arc::new(UiBundle::load(&fixture.bundle()?)?);
    for (path, content_type, expected) in [
        (
            "/",
            "text/html; charset=utf-8",
            b"<canvas></canvas>".as_slice(),
        ),
        (
            "/app.wasm",
            "application/wasm",
            b"\0asm\x01\0\0\0".as_slice(),
        ),
    ] {
        let response = exchange(Some(Arc::clone(&ui)), |address| {
            format!("GET {path} HTTP/1.1\r\nHost: {address}\r\n\r\n")
        })
        .await?;
        let (headers, body) = http_parts(&response)?;
        assert!(headers.starts_with("HTTP/1.1 200 OK"));
        assert!(headers.contains(&format!("Content-Type: {content_type}\r\n")));
        assert!(headers.contains("Content-Security-Policy:"));
        assert_eq!(body, expected);
    }
    for path in ["/healthz", "/api/hepta/runtime"] {
        let response = exchange(Some(Arc::clone(&ui)), |address| {
            format!("GET {path} HTTP/1.1\r\nHost: {address}\r\n\r\n")
        })
        .await?;
        let (headers, body) = http_parts(&response)?;
        assert!(headers.starts_with("HTTP/1.1 200 OK"));
        let value: serde_json::Value = serde_json::from_slice(body)?;
        assert_eq!(value["product"], "hepta");
    }
    let wire = exchange(Some(Arc::clone(&ui)), |address| format!("GET /api/hepta/runtime HTTP/1.1\r\nHost: {address}\r\nAccept: application/x-hepta-wire; version=2\r\n\r\n")).await?;
    let (headers, body) = http_parts(&wire)?;
    assert!(headers.contains("application/x-hepta-wire; version=2"));
    let _ = codex_hepta_wire::WireEnvelopeV2::decode(body)?;
    for (method, path, expected) in [("POST", "/", "405"), ("GET", "/unlisted.js", "404")] {
        let response = exchange(Some(Arc::clone(&ui)), |address| {
            format!("{method} {path} HTTP/1.1\r\nHost: {address}\r\n\r\n")
        })
        .await?;
        assert!(
            http_parts(&response)?
                .0
                .starts_with(&format!("HTTP/1.1 {expected}"))
        );
    }
    let missing = exchange(/*ui*/ None, |address| {
        format!("GET / HTTP/1.1\r\nHost: {address}\r\n\r\n")
    })
    .await?;
    assert!(http_parts(&missing)?.0.starts_with("HTTP/1.1 503"));
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn rebinding_and_cross_origin_are_denied_before_ui_or_runtime_dispatch() -> Result<()> {
    let fixture = Fixture::new()?;
    let ui = Arc::new(UiBundle::load(&fixture.bundle()?)?);
    for path in [
        "/",
        "/app.wasm",
        "/healthz",
        "/api/hepta/runtime",
        "/api/hepta/owner-status",
    ] {
        let response = exchange(Some(Arc::clone(&ui)), |_| {
            format!("GET {path} HTTP/1.1\r\nHost: attacker.example\r\n\r\n")
        })
        .await?;
        assert!(http_parts(&response)?.0.starts_with("HTTP/1.1 403"));
        let response = exchange(Some(Arc::clone(&ui)), |address| {
            format!(
                "GET {path} HTTP/1.1\r\nHost: {address}\r\nOrigin: https://attacker.example\r\n\r\n"
            )
        })
        .await?;
        assert!(http_parts(&response)?.0.starts_with("HTTP/1.1 403"));
    }
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn actual_entry_serves_verified_ui_and_not_attached_without_initializing_legacy_state()
-> Result<()> {
    let fixture = Fixture::new()?;
    let bundle = fixture.bundle()?;
    let missing_state = fixture.0.join("missing-owner-state");
    let root = codex_hepta_paths::HeptaStateRoot::parse(&missing_state)?;
    let reservation = std::net::TcpListener::bind("127.0.0.1:0")?;
    let address = reservation.local_addr()?;
    drop(reservation);
    let server = tokio::spawn(crate::run_native_gateway(crate::NativeGatewayOptions {
        listen_addr: address,
        state_root: root.clone(),
        ui_bundle: Some(bundle),
    }));
    struct Stop(tokio::task::JoinHandle<Result<()>>);
    impl Drop for Stop {
        fn drop(&mut self) {
            self.0.abort();
        }
    }
    let server = Stop(server);
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        loop {
            if tokio::net::TcpStream::connect(address).await.is_ok() {
                break;
            }
            assert!(!server.0.is_finished(), "actual gateway startup failed");
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    for (method, path, status) in [
        ("GET", "/", "200"),
        ("GET", "/api/hepta/owner-status", "200"),
        ("GET", "/healthz", "503"),
        ("GET", "/api/hepta/runtime", "503"),
        ("POST", "/api/hepta/owner-status", "405"),
    ] {
        use tokio::io::AsyncReadExt;
        use tokio::io::AsyncWriteExt;
        let mut stream = tokio::net::TcpStream::connect(address).await?;
        stream
            .write_all(format!("{method} {path} HTTP/1.1\r\nHost: {address}\r\n\r\n").as_bytes())
            .await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        let (headers, body) = http_parts(&bytes)?;
        assert!(headers.starts_with(&format!("HTTP/1.1 {status}")));
        if path == "/" {
            assert_eq!(body, b"<canvas></canvas>");
        }
        if method == "GET" && path == "/api/hepta/owner-status" {
            assert_eq!(
                serde_json::from_slice::<serde_json::Value>(body)?,
                serde_json::json!({
                    "schema":"hepta.owner-lease-observation.v1","observation":{"status":"not_attached"}
                })
            );
        }
        assert!(!String::from_utf8_lossy(body).contains("missing-owner-state"));
    }
    assert!(
        !missing_state.exists(),
        "UI inspection must not bootstrap state"
    );
    drop(server);
    assert!(
        crate::run_native_gateway(crate::NativeGatewayOptions {
            listen_addr: address,
            state_root: root,
            ui_bundle: None,
        })
        .await
        .is_err(),
        "no-bundle legacy startup must still reject missing state"
    );
    assert!(!missing_state.exists());
    Ok(())
}
