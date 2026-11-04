//! Compiled ELF fixtures exercise the real adapter's sealed-object and pipe path.
//! The fixture is not a Chain node or evidence of model/ledger/owner acceptance.
use super::super::PonInvocation;
use super::super::PonLocalProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use std::fs;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

type TestResult = Result<(), Box<dyn std::error::Error>>;

const CHILD: &str = include_str!("../tests/fixtures/pon_pipe.c");
const PRELOAD: &str = include_str!("../tests/fixtures/pon_preload.c");

fn prepare_native_fixture(
    runfile_variable: &str,
    source: &str,
    binary: &Path,
    flags: &[&str],
) -> TestResult {
    if option_env!("BAZEL_PACKAGE").is_some() {
        let runfile = std::env::var_os(runfile_variable).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::NotFound,
                format!("missing declared Bazel fixture runfile: {runfile_variable}"),
            )
        })?;
        fs::copy(runfile, binary)?;
    } else {
        let source_path = binary.with_extension("c");
        fs::write(&source_path, source)?;
        let output = Command::new("cc")
            .args(flags)
            .arg(&source_path)
            .arg("-o")
            .arg(binary)
            .output()?;
        if !output.status.success() {
            return Err(
                io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
            );
        }
    }
    Ok(())
}

fn fixture(
    timeout: Duration,
) -> Result<(tempfile::TempDir, PonLocalProviderEffectAdapter), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let binary = root.join("pipe_fixture");
    prepare_native_fixture(
        "HEPTA_PON_TEST_PIPE_FIXTURE",
        CHILD,
        &binary,
        &["-std=c11", "-O0", "-Wall", "-Wextra", "-Werror"],
    )?;
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o700))?;
    let binary_sha256 = Sha256Digest::for_bytes(&fs::read(&binary)?);
    fs::write(root.join("native.sqlite"), b"fixture-not-a-ledger")?;
    let adapter = PonLocalProviderEffectAdapter {
        binary,
        binary_sha256,
        store: root,
        state_backend: "authenticated-v1".into(),
        genesis_time: 1,
        evaluation_policy: "fixture".into(),
        task_profile: "fixture".into(),
        model_profile: "fixture".into(),
        workers: 1,
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}01", "00".repeat(63)),
        timeout,
    };
    Ok((directory, adapter))
}

#[tokio::test]
async fn sealed_adapter_success_observes_full_payload_and_eof() -> TestResult {
    let (_directory, adapter) = fixture(Duration::from_secs(2))?;
    let result =
        tokio::task::spawn_blocking(move || adapter.invoke("packet-status", &vec![1; 1024 * 1024]))
            .await?;
    match result {
        PonInvocation::Value(value) => assert_eq!(value["bytes"], 1024 * 1024),
        _ => panic!("complete sealed ELF exchange failed"),
    }
    Ok(())
}

#[tokio::test]
async fn sealed_adapter_blocked_stdin_and_descendant_obey_deadline() -> TestResult {
    for operation in ["blocked-stdin", "descendant"] {
        let (_directory, adapter) = fixture(Duration::from_millis(500))?;
        let started = Instant::now();
        let result =
            tokio::task::spawn_blocking(move || adapter.invoke(operation, &vec![1; 1024 * 1024]))
                .await?;
        assert!(matches!(result, PonInvocation::Unknown));
        assert!(started.elapsed() < Duration::from_secs(2));
    }
    Ok(())
}

#[tokio::test]
async fn sealed_adapter_output_limits_nonzero_and_partial_are_unknown() -> TestResult {
    let (_directory, adapter) = fixture(Duration::from_secs(2))?;
    for operation in ["stdout-overrun", "stderr-overrun", "submit", "partial-json"] {
        let adapter = adapter.clone();
        let result =
            tokio::task::spawn_blocking(move || adapter.invoke(operation, b"packet")).await?;
        assert!(matches!(result, PonInvocation::Unknown));
    }
    Ok(())
}

#[tokio::test]
async fn sealed_adapter_dispatch_retains_preentry_versus_unknown() -> TestResult {
    let (_directory, adapter) = fixture(Duration::from_secs(2))?;
    let key = ProviderEffectKey::for_operation("pon-fixture", "run", "step")
        .map_err(|error| io::Error::other(format!("{error:?}")))?;
    let intent = ProviderEffectIntent::new(key, Sha256Digest::for_bytes(b"packet"));
    let current = adapter.clone();
    let accepted_intent = intent.clone();
    let outcome = tokio::task::spawn_blocking(move || {
        current.dispatch_blocking(accepted_intent, b"packet".to_vec())
    })
    .await?;
    assert!(matches!(outcome, ProviderEffectDispatch::Unknown));
    let outcome = tokio::task::spawn_blocking(move || {
        adapter.dispatch_blocking(intent, b"different-wire".to_vec())
    })
    .await?;
    assert!(matches!(
        outcome,
        ProviderEffectDispatch::NotDispatched { .. }
    ));
    Ok(())
}

#[tokio::test]
async fn sealed_adapter_child_environment_is_closed() -> TestResult {
    let (_directory, adapter) = fixture(Duration::from_secs(2))?;
    let result =
        tokio::task::spawn_blocking(move || adapter.invoke("environment", b"packet")).await?;
    match result {
        PonInvocation::Value(value) => {
            assert_eq!(value, serde_json::json!({"isolated": true, "bytes": 6}));
        }
        _ => panic!("sealed environment observation failed"),
    }
    Ok(())
}

#[tokio::test]
async fn sealed_exchange_strips_real_preload_before_execution() -> TestResult {
    let (directory, adapter) = fixture(Duration::from_secs(3))?;
    let library = directory.path().join("preload.so");
    let marker = directory.path().join("preload-entered");
    prepare_native_fixture(
        "HEPTA_PON_TEST_PRELOAD_FIXTURE",
        PRELOAD,
        &library,
        &[
            "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
        ],
    )?;
    let executable = super::super::pon_executable::PinnedExecutable::prepare(
        &adapter.binary,
        adapter.binary_sha256.as_str(),
        Instant::now() + Duration::from_secs(3),
    )?;
    // Positive attack control: the exact sealed ELF still loads an ambient DSO
    // without the exchange boundary. This control never touches process-global
    // environment or another test's files.
    let mut unisolated = Command::new(executable.path());
    unisolated
        .arg("environment")
        .env_clear()
        .env("LD_PRELOAD", &library)
        .env("HEPTA_PON_TEST_MARKER", &marker);
    let control = unisolated.output()?;
    assert!(control.status.success());
    assert_eq!(fs::read(&marker)?, b"loaded");
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&control.stdout)?,
        serde_json::json!({"isolated": false, "bytes": 0}),
    );
    fs::remove_file(&marker)?;
    let result = super::run(
        unisolated,
        b"packet",
        Instant::now() + Duration::from_secs(3),
        super::super::MAX_PON_PROCESS_OUTPUT_BYTES,
    )
    .await;
    match result {
        super::Outcome::Complete(stdout) => assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&stdout)?,
            serde_json::json!({"isolated": true, "bytes": 6}),
        ),
        _ => panic!("isolated sealed exchange failed"),
    }
    assert!(!marker.try_exists()?);
    Ok(())
}
