use super::spawn_setup_helper;
use crate::process::ConsoleMode;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use serde::Deserialize;
use serde::Serialize;
use std::fs;
use std::io::Write;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::Storage::FileSystem as files;
use windows_sys::Win32::System::Threading as threading;

#[path = "setup_process_tests_support.rs"]
mod support;
use support::Events;
use support::NativeChild;
use support::Observation;
use support::Process;

const DRIVER: &str = "hepta-setup-handle-driver.exe";
const PROBE: &str = "hepta-setup-handle-probe.exe";
const CONFIG: &str = "hepta-setup-handle-fixture.json";
const DRIVER_MS: u32 = 30_000;

#[derive(Clone, Deserialize, Serialize)]
struct Config {
    role: String,
    test_name: String,
    no_window: bool,
    nonce: String,
    events: [String; 3],
    ambient_event: usize,
    ambient_writer: usize,
}

#[derive(Debug, Deserialize, Serialize)]
struct ProbeReport {
    nonce: String,
    pid: u32,
    observation: Observation,
}

#[derive(Deserialize, Serialize)]
struct DriverReport {
    nonce: String,
    pid: u32,
    complete: bool,
    children_natively_waited: usize,
    error: Option<String>,
}

fn write_new(path: &Path, value: &impl Serialize) -> Result<()> {
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    output.write_all(&serde_json::to_vec(value)?)?;
    output.sync_all()?;
    Ok(())
}

fn fixture(parent: &Path, role: &str, config: &Config) -> Result<PathBuf> {
    let directory = parent.join(role);
    fs::create_dir(&directory)?;
    let name = if config.role == "driver" {
        DRIVER
    } else {
        PROBE
    };
    let executable = directory.join(name);
    let mut input = fs::File::open(std::env::current_exe()?)?;
    let expected_bytes = input.metadata()?.len();
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&executable)?;
    ensure!(
        std::io::copy(&mut input, &mut output)? == expected_bytes,
        "incomplete fixture binary copy"
    );
    output.sync_all()?;
    drop(output);
    write_new(&directory.join(CONFIG), config)?;
    Ok(executable)
}

fn event_names(nonce: &str, role: &str) -> [String; 3] {
    ["start", "ready", "release"]
        .map(|phase| format!("Local\\hepta-setup-handles-{nonce}-{role}-{phase}"))
}

fn read_config(executable: &Path, role: &str, no_window: bool, test_name: &str) -> Result<Config> {
    let directory = executable
        .parent()
        .context("fixture executable directory")?;
    let path = directory.join(CONFIG);
    ensure!(
        fs::symlink_metadata(&path)?.file_type().is_file(),
        "fixture configuration must be a regular owned file"
    );
    let config: Config = serde_json::from_slice(&fs::read(path)?)?;
    ensure!(
        config.role == role && config.no_window == no_window && config.test_name == test_name,
        "fixture role/mode/filter mismatch"
    );
    ensure!(
        !config.nonce.is_empty()
            && config.nonce.len() < 100
            && config
                .nonce
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_')),
        "invalid fixture nonce"
    );
    let label = directory
        .file_name()
        .and_then(|value| value.to_str())
        .context("fixture directory role")?;
    ensure!(
        (role == "driver" && label == "driver")
            || (role == "probe" && matches!(label, "baseline" | "candidate")),
        "unexpected fixture directory role"
    );
    ensure!(
        config.events == event_names(&config.nonce, label),
        "control event names are not bound to this fixture"
    );
    ensure!(
        std::env::args_os().skip(1).collect::<Vec<_>>() == [std::ffi::OsString::from(test_name)],
        "fixture must select only its own original test filter"
    );
    Ok(config)
}

fn await_start(config: &Config) -> Result<()> {
    let start = support::open_event(&config.events[0])?;
    // Both probes start before the baseline is measured. The candidate must not
    // spend its Ready budget while waiting for the baseline's native termination.
    // The separately owned driver bounds this coordination and never grants Start
    // after its own termination; a missing Start still fails this bounded wait.
    let start_ms = if config.role == "probe" {
        DRIVER_MS
    } else {
        support::READY_MS
    };
    ensure!(
        support::wait(&start, start_ms) == foundation::WAIT_OBJECT_0,
        "fixture Start was not granted"
    );
    // Do not leave control handles in slots that could alias omitted ambient handles.
    drop(start);
    Ok(())
}

fn probe(executable: &Path, config: &Config) -> Result<()> {
    ensure!(
        config.ambient_event != 0
            && config.ambient_writer != 0
            && config.ambient_event != config.ambient_writer,
        "invalid distinct ambient handles"
    );
    await_start(config)?;
    // No further file/control handle is opened until both ambient operations were attempted.
    let observation = support::observe(
        config.ambient_event,
        config.ambient_writer,
        config.nonce.as_bytes(),
    );
    let report = ProbeReport {
        nonce: config.nonce.clone(),
        pid: std::process::id(),
        observation,
    };
    write_new(
        &executable
            .parent()
            .context("probe directory")?
            .join("result.json"),
        &report,
    )?;
    let ready = support::open_event(&config.events[1])?;
    let release = support::open_event(&config.events[2])?;
    support::signal(&ready)?;
    // Remaining alive is an explicit state, not a sleep intended to outlast a leak timer.
    ensure!(
        support::wait(&release, support::EXIT_MS) == foundation::WAIT_OBJECT_0,
        "probe Release was not granted"
    );
    Ok(())
}

fn probe_report(path: &Path, config: &Config, child: &NativeChild) -> Result<ProbeReport> {
    let report: ProbeReport = serde_json::from_slice(&fs::read(
        path.parent().context("probe path")?.join("result.json"),
    )?)?;
    ensure!(
        child.id() != 0 && report.pid == child.id() && report.nonce == config.nonce,
        "report is not bound to the retained process/nonce"
    );
    Ok(report)
}

fn run_pair(directory: &Path, config: &Config) -> Result<()> {
    let ambient_event = support::event(/*name*/ None, /*inheritable*/ true)?;
    let (read, writer) = support::ambient_pipe()?;
    let mut baseline_config = config.clone();
    baseline_config.role = "probe".to_string();
    baseline_config.events = event_names(&config.nonce, "baseline");
    baseline_config.ambient_event = support::handle(&ambient_event) as usize;
    baseline_config.ambient_writer = support::handle(&writer) as usize;
    let mut candidate_config = baseline_config.clone();
    candidate_config.events = event_names(&config.nonce, "candidate");
    let baseline_events = Events::new(&baseline_config.events)?;
    let candidate_events = Events::new(&candidate_config.events)?;
    let baseline_exe = fixture(directory, "baseline", &baseline_config)?;
    let candidate_exe = fixture(directory, "candidate", &candidate_config)?;
    let mut command = Command::new(&baseline_exe);
    command
        .arg(&config.test_name)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if config.no_window {
        command.creation_flags(threading::CREATE_NO_WINDOW);
    }
    let mut baseline = NativeChild::new(Process::Command(command.spawn()?), baseline_events);
    let mode = if config.no_window {
        ConsoleMode::NoWindow
    } else {
        ConsoleMode::Inherit
    };
    let mut candidate = NativeChild::new(
        Process::Helper(spawn_setup_helper(&candidate_exe, &config.test_name, mode)?),
        candidate_events,
    );
    // Both children were created while these exact same ambient objects were inheritable.
    drop(writer);

    support::signal(&baseline.events.start)?;
    baseline.ready()?;
    let baseline_report = probe_report(&baseline_exe, &baseline_config, &baseline)?;
    eprintln!(
        "setup-handle baseline {}",
        serde_json::to_string(&baseline_report)?
    );
    ensure!(
        baseline_report.observation.event_set
            && baseline_report.observation.write_ok
            && baseline_report.observation.written as usize == config.nonce.len(),
        "original Command did not demonstrate actual handle propagation"
    );
    ensure!(
        support::wait(&ambient_event, /*milliseconds*/ 0) == foundation::WAIT_OBJECT_0,
        "baseline did not set the same retained event"
    );
    support::read_exact_nonce(&read, config.nonce.as_bytes())?;
    baseline.alive()?;
    ensure!(
        support::peek(&read) == (true, 0, 0),
        "baseline did not retain the same pipe writer while alive"
    );
    support::signal(&baseline.events.release)?;
    baseline.finish(support::EXIT_MS)?;
    support::reset(&ambient_event)?;

    support::signal(&candidate.events.start)?;
    candidate.ready()?;
    let candidate_report = probe_report(&candidate_exe, &candidate_config, &candidate)?;
    eprintln!(
        "setup-handle candidate {}",
        serde_json::to_string(&candidate_report)?
    );
    let observation = &candidate_report.observation;
    // Keep numeric-handle attempts as diagnostics: the child runtime can reuse an
    // omitted handle's slot for another object. The retained parent event and
    // pipe below prove object identity while the candidate is still alive.
    ensure!(
        support::wait(&ambient_event, /*milliseconds*/ 0) == foundation::WAIT_TIMEOUT,
        "candidate set the same retained ambient event"
    );
    candidate.alive()?;
    let (connected, pipe_error, _) = support::peek(&read);
    ensure!(
        !connected && pipe_error == foundation::ERROR_BROKEN_PIPE,
        "ambient pipe writer survived while candidate was alive"
    );
    candidate.alive()?;
    ensure!(
        observation.std_handles[0] != 0
            && observation
                .std_handles
                .iter()
                .all(|handle| *handle == observation.std_handles[0]),
        "candidate did not inherit one shared standard handle"
    );
    ensure!(
        observation.std_types == [files::FILE_TYPE_CHAR; 3]
            && observation.stdin_eof
            && observation.stdout_write_ok,
        "candidate NUL standard streams did not retain their contract"
    );
    support::signal(&candidate.events.release)?;
    candidate.finish(support::EXIT_MS)?;
    Ok(())
}

fn isolated_parent(no_window: bool, test_name: &str) -> Result<()> {
    let temporary = tempfile::Builder::new()
        .prefix("hepta-setup-handles-")
        .tempdir()?;
    let nonce = temporary
        .path()
        .file_name()
        .and_then(|value| value.to_str())
        .context("fixture nonce")?
        .to_string();
    let config = Config {
        role: "driver".to_string(),
        test_name: test_name.to_string(),
        no_window,
        nonce: nonce.clone(),
        events: event_names(&nonce, "driver"),
        ambient_event: 0,
        ambient_writer: 0,
    };
    let events = Events::new(&config.events)?;
    let executable = fixture(temporary.path(), "driver", &config)?;
    let job = JobObject::create_without_breakaway()?;
    let mut driver = NativeChild::new(
        Process::Helper(spawn_setup_helper(
            &executable,
            test_name,
            ConsoleMode::NoWindow,
        )?),
        events,
    );
    let result = (|| -> Result<()> {
        // Before this Start, the driver cannot create either probe descendant.
        support::assign_job(&job, &driver)?;
        support::signal(&driver.events.start)?;
        driver.finish(DRIVER_MS)?;
        let report: DriverReport = serde_json::from_slice(&fs::read(
            executable
                .parent()
                .context("driver directory")?
                .join("result.json"),
        )?)?;
        ensure!(
            report.pid == driver.id()
                && report.nonce == nonce
                && report.complete
                && report.children_natively_waited == 2
                && report.error.is_none(),
            "driver did not finish both retained children"
        );
        Ok(())
    })();
    // Only this test's no-breakaway job is terminated if a driver fails or times out.
    let termination = if result.is_err() {
        job.terminate().map_err(anyhow::Error::from)
    } else {
        Ok(())
    };
    drop(driver);
    let drained = support::require_empty_job(&job);
    if let Err(error) = &drained {
        eprintln!("setup-handle owned job cleanup failed: {error:#}");
    }
    // Preserve each actual native observation in the outer test's captured output.
    // Read only this fixture's files, after all owned descendants have terminated.
    for role in ["baseline", "candidate"] {
        let path = executable
            .parent()
            .context("driver evidence directory")?
            .join(role)
            .join("result.json");
        match fs::read_to_string(&path) {
            Ok(report) => eprintln!("setup-handle {role} native report: {report}"),
            Err(error) => eprintln!("setup-handle {role} native report unavailable: {error}"),
        }
    }
    result.and(termination).and(drained)
}

fn dispatch(no_window: bool, test_name: &str) -> Result<()> {
    let executable = std::env::current_exe()?;
    let name = executable
        .file_name()
        .and_then(|value| value.to_str())
        .context("test executable name")?;
    match name {
        DRIVER => {
            let config = read_config(&executable, "driver", no_window, test_name)?;
            ensure!(
                config.ambient_event == 0 && config.ambient_writer == 0,
                "driver must not take probe handles"
            );
            await_start(&config)?;
            let result = run_pair(executable.parent().context("driver path")?, &config);
            let report = DriverReport {
                nonce: config.nonce,
                pid: std::process::id(),
                complete: result.is_ok(),
                children_natively_waited: if result.is_ok() { 2 } else { 0 },
                error: result.as_ref().err().map(|error| format!("{error:#}")),
            };
            write_new(
                &executable
                    .parent()
                    .context("driver path")?
                    .join("result.json"),
                &report,
            )?;
            result
        }
        PROBE => {
            let config = read_config(&executable, "probe", no_window, test_name)?;
            probe(&executable, &config)
        }
        _ if name.starts_with("hepta-setup-handle-") => bail!("unknown fixture executable role"),
        _ => {
            ensure!(
                !executable
                    .parent()
                    .context("test executable directory")?
                    .join(CONFIG)
                    .try_exists()?,
                "fixture configuration without a recognized executable role"
            );
            isolated_parent(no_window, test_name)
        }
    }
}

#[test]
fn inherit_console_setup_does_not_inherit_ambient_handles() {
    dispatch(
        /*no_window*/ false,
        "setup_process::tests::inherit_console_setup_does_not_inherit_ambient_handles",
    )
    .unwrap_or_else(|error| panic!("setup handle-list control failed: {error:#}"));
}

#[test]
fn no_window_setup_does_not_inherit_ambient_handles() {
    dispatch(
        /*no_window*/ true,
        "setup_process::tests::no_window_setup_does_not_inherit_ambient_handles",
    )
    .unwrap_or_else(|error| panic!("setup handle-list control failed: {error:#}"));
}
