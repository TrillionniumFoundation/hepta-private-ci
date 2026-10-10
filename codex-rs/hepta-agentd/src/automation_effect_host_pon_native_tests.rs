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
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

type TestResult = Result<(), Box<dyn std::error::Error>>;

const CHILD: &str = r#"
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/types.h>
#include <unistd.h>

extern char **environ;

static void delay_ms(long ms) {
    struct timespec t = { ms / 1000, (ms % 1000) * 1000000 };
    while (nanosleep(&t, &t) != 0 && errno == EINTR) {}
}
static int write_all(int fd, const char *p, size_t n) {
    while (n != 0) {
        ssize_t k = write(fd, p, n);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return 1;
        p += k; n -= (size_t)k;
    }
    return 0;
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (strcmp(argv[1], "blocked-stdin") == 0) {
        delay_ms(3000); return 0;
    }
    char buffer[4096];
    unsigned long total = 0;
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buffer, sizeof buffer);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return 3;
        if (n == 0) break;
        total += (unsigned long)n;
    }
    if (strcmp(argv[1], "environment") == 0) {
        size_t count = 0;
        while (environ[count] != NULL) ++count;
        const char *locale = getenv("LC_ALL");
        const char *zone = getenv("TZ");
        int isolated = count == 2 && locale != NULL && zone != NULL &&
            strcmp(locale, "C") == 0 && strcmp(zone, "UTC") == 0;
        int n = snprintf(buffer, sizeof buffer,
            "{\"isolated\":%s,\"bytes\":%lu}", isolated ? "true" : "false", total);
        if (n <= 0 || (size_t)n >= sizeof buffer) return 6;
        return write_all(STDOUT_FILENO, buffer, (size_t)n);
    }
    if (strcmp(argv[1], "descendant") == 0) {
        pid_t child = fork();
        if (child < 0) return 4;
        if (child == 0) { delay_ms(1250); _exit(0); }
    }
    if (strcmp(argv[1], "submit") == 0) return 7;
    if (strcmp(argv[1], "partial-json") == 0) {
        return write_all(STDOUT_FILENO, "{", 1);
    }
    if (strcmp(argv[1], "stdout-overrun") == 0 ||
        strcmp(argv[1], "stderr-overrun") == 0) {
        int fd = strcmp(argv[1], "stdout-overrun") == 0 ? STDOUT_FILENO : STDERR_FILENO;
        memset(buffer, 'x', sizeof buffer);
        for (int i = 0; i < 16; ++i) {
            if (write_all(fd, buffer, sizeof buffer)) return 5;
        }
        if (write_all(fd, "x", 1)) return 5;
    }
    int n = snprintf(buffer, sizeof buffer, "{\"bytes\":%lu}", total);
    if (n <= 0 || (size_t)n >= sizeof buffer) return 6;
    return write_all(STDOUT_FILENO, buffer, (size_t)n);
}
"#;

fn fixture(
    timeout: Duration,
) -> Result<(tempfile::TempDir, PonLocalProviderEffectAdapter), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let source = root.join("pipe_fixture.c");
    let binary = root.join("pipe_fixture");
    fs::write(&source, CHILD)?;
    let output = Command::new("cc")
        .args(["-std=c11", "-O0", "-Wall", "-Wextra", "-Werror"])
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into());
    }
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
    let source = directory.path().join("preload.c");
    let library = directory.path().join("preload.so");
    let marker = directory.path().join("preload-entered");
    fs::write(
        &source,
        r#"
#include <stdio.h>
#include <stdlib.h>
__attribute__((constructor)) static void injected(void) {
    const char *path = getenv("HEPTA_PON_TEST_MARKER");
    if (path == NULL) return;
    FILE *file = fopen(path, "wb");
    if (file != NULL) { fputs("loaded", file); fclose(file); }
}
"#,
    )?;
    let built = Command::new("cc")
        .args([
            "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
        ])
        .arg(&source)
        .arg("-o")
        .arg(&library)
        .output()?;
    if !built.status.success() {
        return Err(io::Error::other(String::from_utf8_lossy(&built.stderr).into_owned()).into());
    }
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
