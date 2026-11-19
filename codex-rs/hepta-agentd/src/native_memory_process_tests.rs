//! Process-only fixtures never import torch or claim successful inference.
use super::execute;
use crate::native_memory_test_support::config;
use codex_hepta_types::Digest32;
use std::time::Duration;
use std::time::Instant;

fn prepared_worker(temp: &tempfile::TempDir) -> anyhow::Result<crate::NativeMemoryModelConfigV1> {
    let mut c = config(temp.path());
    let python = std::process::Command::new("python3")
        .args(["-c", "import sys; print(sys.executable)"])
        .output()?;
    assert!(python.status.success());
    c.python = String::from_utf8(python.stdout)?.trim().into();
    for path in [
        "scripts/memory_cell_native",
        "scripts/memory_cell_network",
        "receipts",
    ] {
        std::fs::create_dir_all(temp.path().join(path))?;
    }
    let worker = b"import time\ntime.sleep(30)\n";
    let launcher = b"import runpy,sys\nrunpy.run_path(sys.argv[-1],run_name='__main__')\n";
    std::fs::write(
        temp.path()
            .join("scripts/memory_cell_native/native_worker.py"),
        worker,
    )?;
    std::fs::write(
        temp.path()
            .join("scripts/memory_cell_network/model_child.py"),
        launcher,
    )?;
    c.pins.worker_sha256 = Digest32::of_bytes(worker).to_string();
    c.pins.launcher_sha256 = Digest32::of_bytes(launcher).to_string();
    Ok(c)
}

#[tokio::test]
async fn native_memory_timeout_includes_blocked_stdin_and_keeps_failure() -> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 100;
    // A 64 KiB payload can fit entirely in a Unix pipe without blocking.
    let input = vec![b'x'; 2 * 1024 * 1024];
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    let started = Instant::now();
    assert!(
        execute(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            || Ok(())
        )
        .await
        .is_err()
    );
    assert!(started.elapsed() < Duration::from_secs(3));
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert!(
        report["timed_out"] == true && report["stdin_completed"] == false,
        "unexpected child process receipt: {report}"
    );
    assert!(directory.join("stderr.log").is_file());
    Ok(())
}

#[tokio::test]
async fn native_memory_daemon_lifetime_cancels_child_and_keeps_failure() -> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let c = prepared_worker(&temp)?;
    let cancellation = tokio_util::sync::CancellationToken::new();
    let other = cancellation.clone();
    let cancel = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(100));
        other.cancel();
    });
    let started = Instant::now();
    let input = b"closed fixture".to_vec();
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    assert!(execute(&c, input, &cancellation, || Ok(())).await.is_err());
    cancel.join().unwrap();
    assert!(started.elapsed() < Duration::from_secs(3));
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert!(report["owner_cancelled"] == true);
    Ok(())
}

fn replace_worker(c: &mut crate::NativeMemoryModelConfigV1, source: &[u8]) -> std::io::Result<()> {
    std::fs::write(
        c.repo.join("scripts/memory_cell_native/native_worker.py"),
        source,
    )?;
    c.pins.worker_sha256 = Digest32::of_bytes(source).to_string();
    Ok(())
}

fn receipt_directory(c: &crate::NativeMemoryModelConfigV1, input: &[u8]) -> std::path::PathBuf {
    c.receipt_directory
        .join(Digest32::of_bytes(input).to_string())
}

#[tokio::test]
async fn native_memory_real_launcher_delivers_eof_and_returns_successful_worker_bytes()
-> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 3000;
    let actual_launcher =
        codex_utils_cargo_bin::find_resource!("../../scripts/memory_cell_network/model_child.py")
            .expect("declared production launcher resource must exist");
    let launcher = std::fs::read(actual_launcher).unwrap();
    std::fs::write(
        c.repo.join("scripts/memory_cell_network/model_child.py"),
        &launcher,
    )
    .unwrap();
    c.pins.launcher_sha256 = Digest32::of_bytes(&launcher).to_string();
    replace_worker(
        &mut c,
        b"import sys\nvalue = sys.stdin.buffer.read()\nsys.stdout.buffer.write(value)\n",
    )?;
    let input = b"complete input followed by EOF".to_vec();
    let directory = receipt_directory(&c, &input);
    let output = execute(
        &c,
        input.clone(),
        &tokio_util::sync::CancellationToken::new(),
        || Ok(()),
    )
    .await
    .unwrap();
    assert_eq!(output, input);
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert_eq!(report["stdin_completed"], true);
    assert_eq!(report["exit_code"], 0);
    assert_eq!(report["timed_out"], false);
    assert_eq!(report["process_group_error"], serde_json::Value::Null);
    Ok(())
}

#[tokio::test]
async fn native_memory_does_not_inherit_ambient_secret_or_python_path() -> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 3000;
    replace_worker(
        &mut c,
        br#"import json,os,sys
sys.stdin.buffer.read()
print(json.dumps({'environment': dict(os.environ)}), flush=True)
"#,
    )?;
    let input = b"environment fixture".to_vec();
    let directory = receipt_directory(&c, &input);
    let environment = [
        ("PATH", "/usr/bin:/bin"),
        ("GH_TOKEN", "hepta-synthetic-secret-canary"),
        ("AWS_SESSION_TOKEN", "hepta-synthetic-secret-canary"),
        ("PYTHONPATH", "/untrusted/synthetic/module/path"),
        ("HF_HUB_OFFLINE", "0"),
    ]
    .map(|(key, value)| (key.into(), value.into()));
    // The fixture launcher has no authority/parent-death receipt. The recorded
    // actual child output, not this intentional final refusal, is the assertion.
    assert!(
        super::execute_with_environment(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            environment,
            || Ok(()),
        )
        .await
        .is_err()
    );
    let raw = std::fs::read(directory.join("stdout.json")).unwrap();
    let value: serde_json::Value = serde_json::from_slice(&raw).unwrap();
    let env = value["environment"].as_object().unwrap();
    assert!(
        !String::from_utf8(raw)
            .unwrap()
            .contains("hepta-synthetic-secret-canary")
    );
    for key in ["GH_TOKEN", "AWS_SESSION_TOKEN", "PYTHONPATH"] {
        assert!(!env.contains_key(key));
    }
    assert_eq!(env["HF_HUB_OFFLINE"], "1");
    assert_eq!(env["TRANSFORMERS_OFFLINE"], "1");
    assert_eq!(env["HF_HUB_DISABLE_TELEMETRY"], "1");
    assert_eq!(env["PATH"], "/usr/bin:/bin");
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        std::fs::metadata(&directory).unwrap().permissions().mode() & 0o777,
        0o700
    );
    for artifact in std::fs::read_dir(&directory).unwrap() {
        assert_eq!(
            artifact.unwrap().metadata().unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    Ok(())
}

async fn assert_descendant_stopped(pid: i32) {
    let until = Instant::now() + Duration::from_secs(2);
    loop {
        // SAFETY: signal 0 only checks the fixture process's existence.
        if unsafe { libc::kill(pid, 0) } != 0 {
            return;
        }
        #[cfg(target_os = "linux")]
        if let Ok(stat) = std::fs::read_to_string(format!("/proc/{pid}/stat"))
            && stat
                .rsplit_once(") ")
                .is_some_and(|(_, tail)| tail.starts_with("Z "))
        {
            // The orphan is stopped; only its adopting process can reap it.
            return;
        }
        if Instant::now() >= until {
            // SAFETY: stop only the recorded fixture child if the assertion fails.
            let _ = unsafe { libc::kill(pid, libc::SIGKILL) };
            panic!("fixture descendant {pid} survived worker cleanup");
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

#[tokio::test]
async fn native_memory_timeout_closes_grandchild_pipes_and_kills_group() -> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 500;
    replace_worker(
        &mut c,
        br#"import subprocess,sys,time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
print(child.pid, flush=True)
time.sleep(30)
"#,
    )?;
    let input = b"grandchild pipe timeout".to_vec();
    let directory = receipt_directory(&c, &input);
    let started = Instant::now();
    assert!(
        execute(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            || Ok(())
        )
        .await
        .is_err()
    );
    assert!(started.elapsed() < Duration::from_secs(3));
    let pid = std::fs::read_to_string(directory.join("stdout.json"))
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert_eq!(report["timed_out"], true);
    assert_descendant_stopped(pid).await;
    Ok(())
}

#[tokio::test]
async fn native_memory_direct_exit_cannot_leave_a_descendant_holding_pipes() -> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 500;
    replace_worker(
        &mut c,
        br#"import subprocess,sys
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
print(child.pid, flush=True)
"#,
    )?;
    let input = b"direct exit inherited pipes".to_vec();
    let directory = receipt_directory(&c, &input);
    let started = Instant::now();
    assert!(
        execute(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            || Ok(())
        )
        .await
        .is_err()
    );
    assert!(started.elapsed() < Duration::from_secs(3));
    let pid = std::fs::read_to_string(directory.join("stdout.json"))
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert_descendant_stopped(pid).await;
    Ok(())
}

#[tokio::test]
async fn native_memory_completed_child_cannot_leave_a_background_descendant() -> anyhow::Result<()>
{
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 3000;
    replace_worker(&mut c, br#"import subprocess,sys
sys.stdin.buffer.read()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
"#)?;
    let input = b"completed child cleanup".to_vec();
    let directory = receipt_directory(&c, &input);
    assert!(
        execute(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            || Ok(())
        )
        .await
        .is_err()
    );
    let pid = std::fs::read_to_string(directory.join("stdout.json"))
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert_eq!(report["exit_code"], 0);
    assert_eq!(report["timed_out"], false);
    assert_descendant_stopped(pid).await;
    Ok(())
}

#[tokio::test]
async fn native_memory_output_flood_stops_at_bound_without_waiting_for_timeout()
-> anyhow::Result<()> {
    let temp = tempfile::tempdir().unwrap();
    let mut c = prepared_worker(&temp)?;
    c.timeout_millis = 10_000;
    replace_worker(
        &mut c,
        b"import os\nwhile True: os.write(1, b'x' * 65536)\n",
    )?;
    let input = b"output bound fixture".to_vec();
    let directory = receipt_directory(&c, &input);
    let started = Instant::now();
    assert!(
        execute(
            &c,
            input,
            &tokio_util::sync::CancellationToken::new(),
            || Ok(())
        )
        .await
        .is_err()
    );
    assert!(started.elapsed() < Duration::from_secs(3));
    assert_eq!(
        std::fs::metadata(directory.join("stdout.json"))
            .unwrap()
            .len(),
        65_537
    );
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("process.json")).unwrap()).unwrap();
    assert_eq!(report["timed_out"], false);
    assert!(
        report["io_error"]
            .as_str()
            .unwrap()
            .contains("exceeds bound")
    );
    Ok(())
}

#[tokio::test]
async fn native_memory_current_guard_runs_after_setup_and_refuses_child_spawn() {
    let temp = tempfile::tempdir().unwrap();
    let c = prepared_worker(&temp).expect("prepare process-only worker");
    let input = b"pre-spawn guard fixture".to_vec();
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    let expected = input.clone();
    let entered = std::cell::Cell::new(false);
    let result = execute(
        &c,
        input,
        &tokio_util::sync::CancellationToken::new(),
        || {
            assert_eq!(
                std::fs::read(directory.join("request.json")).unwrap(),
                expected
            );
            entered.set(true);
            Err("fixture current owner changed before spawn".to_string())
        },
    )
    .await;
    assert_eq!(
        result,
        Err("fixture current owner changed before spawn".to_string())
    );
    assert!(entered.get());
    assert!(!directory.join("process.json").exists());
}

#[tokio::test]
async fn native_memory_cancellation_during_final_guard_refuses_child_spawn() {
    let temp = tempfile::tempdir().unwrap();
    let c = prepared_worker(&temp).expect("prepare process-only worker");
    let input = b"cancel inside final guard fixture".to_vec();
    let directory = c
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    let cancellation = tokio_util::sync::CancellationToken::new();
    let entered = std::cell::Cell::new(false);
    let result = execute(&c, input, &cancellation, || {
        assert!(directory.join("request.json").is_file());
        entered.set(true);
        cancellation.cancel();
        Ok(())
    })
    .await;
    assert!(entered.get());
    assert_eq!(result, Err("native owner is closed".to_string()));
    assert!(!directory.join("process.json").exists());
}
