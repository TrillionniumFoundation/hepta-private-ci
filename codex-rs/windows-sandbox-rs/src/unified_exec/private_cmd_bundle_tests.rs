//! Native challenge for one private, byte-pinned cmd image. This is not
//! qualification of Minimal, arbitrary scripts, system ACL mutation, or ConPTY.

use super::*;
use anyhow::Context;
use pretty_assertions::assert_eq;
use std::io::Write;
use windows_sys::Win32::Security::Cryptography::BCRYPT_ALG_HANDLE;
use windows_sys::Win32::Security::Cryptography::BCRYPT_SHA256_ALGORITHM;
use windows_sys::Win32::Security::Cryptography::BCryptCloseAlgorithmProvider;
use windows_sys::Win32::Security::Cryptography::BCryptHash;
use windows_sys::Win32::Security::Cryptography::BCryptOpenAlgorithmProvider;

fn native_sha256(bytes: &[u8]) -> anyhow::Result<[u8; 32]> {
    struct Algorithm(BCRYPT_ALG_HANDLE);
    impl Drop for Algorithm {
        fn drop(&mut self) {
            // SAFETY: this helper owns the successfully opened algorithm.
            unsafe { BCryptCloseAlgorithmProvider(self.0, 0) };
        }
    }
    let mut handle = std::ptr::null_mut();
    // SAFETY: handle is writable and the algorithm name is a static wide string.
    let status = unsafe {
        BCryptOpenAlgorithmProvider(&mut handle, BCRYPT_SHA256_ALGORITHM, std::ptr::null(), 0)
    };
    anyhow::ensure!(status >= 0, "open native SHA-256: {status:#x}");
    let algorithm = Algorithm(handle);
    let mut digest = [0; 32];
    // SAFETY: every buffer is valid for its supplied length. The output is the
    // fixed 32-byte SHA-256 digest, and no keyed secret is requested.
    let status = unsafe {
        BCryptHash(
            algorithm.0,
            std::ptr::null(),
            0,
            bytes.as_ptr(),
            bytes.len().try_into()?,
            digest.as_mut_ptr(),
            digest.len().try_into()?,
        )
    };
    anyhow::ensure!(status >= 0, "hash native image: {status:#x}");
    Ok(digest)
}

#[test]
fn fixed_cmd_bundle_executes_with_explicit_private_read_roots() -> anyhow::Result<()> {
    let _guard = legacy_process_test_guard();
    let root = tempfile::tempdir()?;
    let bundle = root.path().join("runtime");
    let workspace = root.path().join("workspace");
    let state = root.path().join("state");
    for path in [&bundle, &workspace, &state] {
        fs::create_dir(path)?;
    }
    let system_root = std::env::var_os("SystemRoot").context("native SystemRoot is required")?;
    let source = PathBuf::from(&system_root).join("System32").join("cmd.exe");
    let original =
        fs::read(&source).context("read original system cmd image without changing ACL")?;
    anyhow::ensure!(!original.is_empty(), "system cmd image is empty");
    let source_digest = native_sha256(&original)?;
    let image = bundle.join("cmd.exe");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&image)?;
    file.write_all(&original)?;
    file.sync_all()?;
    drop(file);
    let copied = fs::read(&image)?;
    assert_eq!(
        copied, original,
        "private runtime must preserve every source byte"
    );
    assert_eq!(native_sha256(&copied)?, source_digest);
    let sentinel = bundle.join("read-only-sentinel.txt");
    fs::write(&sentinel, b"PRIVATE-BUNDLE-READONLY\r\n")?;

    let mut profile = PermissionProfile::workspace_write();
    let PermissionProfile::Managed {
        file_system: ManagedFileSystemPermissions::Restricted { entries, .. },
        ..
    } = &mut profile
    else {
        anyhow::bail!("expected restricted managed profile");
    };
    // This challenge has no ambient Root, Minimal, or temporary-directory
    // grant. Only the task workspace is writable; the bundle and state are read.
    entries.clear();
    for (path, access) in [
        (&bundle, FileSystemAccessMode::Read),
        (&state, FileSystemAccessMode::Read),
        (&workspace, FileSystemAccessMode::Write),
    ] {
        entries.push(FileSystemSandboxEntry::new(
            FileSystemPath::Path {
                path: AbsolutePathBuf::from_absolute_path(path)?.into(),
            },
            access,
        ));
    }
    let digest_hex = source_digest
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    eprintln!(
        "fixed cmd challenge source={} image={} bytes={} sha256={digest_hex}; no system ACL writes",
        source.display(),
        image.display(),
        original.len(),
    );
    let script = format!(
        "echo PRIVATE-BUNDLE-CMD& echo PRIVATE-WORKSPACE>allowed.txt& (echo MUTATED)>\"{}\"& if errorlevel 1 (echo PRIVATE-BUNDLE-WRITE-DENIED) else (echo PRIVATE-BUNDLE-WRITE-ALLOWED)& type \"{}\"",
        sentinel.display(),
        sentinel.display(),
    );
    let mut env_map = HashMap::new();
    env_map.insert(
        "SystemRoot".to_string(),
        system_root.to_string_lossy().into_owned(),
    );
    env_map.insert("ComSpec".to_string(), image.display().to_string());
    let runtime = current_thread_runtime();
    runtime.block_on(async {
        let spawned = spawn_windows_sandbox_session_legacy(
            &profile,
            workspace_roots_for(&workspace).as_slice(),
            &state,
            vec![
                image.display().to_string(),
                "/d".to_string(),
                "/q".to_string(),
                "/c".to_string(),
                script,
            ],
            &workspace,
            env_map,
            Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .with_context(|| format!("spawn byte-pinned private cmd; {}", sandbox_log(&state)))?;
        let (stdout, exit_code) =
            collect_stdout_and_exit(spawned, &state, Duration::from_secs(10)).await;
        let stdout = String::from_utf8_lossy(&stdout);
        assert_eq!(exit_code, 0, "private cmd output={stdout:?}");
        for marker in [
            "PRIVATE-BUNDLE-CMD",
            "PRIVATE-BUNDLE-WRITE-DENIED",
            "PRIVATE-BUNDLE-READONLY",
        ] {
            assert!(stdout.contains(marker), "missing {marker}: {stdout:?}");
        }
        assert!(
            !stdout.contains("PRIVATE-BUNDLE-WRITE-ALLOWED"),
            "{stdout:?}"
        );
        Ok::<(), anyhow::Error>(())
    })?;
    assert_eq!(
        fs::read(workspace.join("allowed.txt"))?,
        b"PRIVATE-WORKSPACE\r\n"
    );
    assert_eq!(fs::read(&sentinel)?, b"PRIVATE-BUNDLE-READONLY\r\n");
    assert_eq!(native_sha256(&fs::read(&image)?)?, source_digest);
    assert_eq!(native_sha256(&fs::read(&source)?)?, source_digest);
    Ok(())
}
