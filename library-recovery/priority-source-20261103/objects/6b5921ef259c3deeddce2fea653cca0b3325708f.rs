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
    let mut wrong = options.clone();
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
