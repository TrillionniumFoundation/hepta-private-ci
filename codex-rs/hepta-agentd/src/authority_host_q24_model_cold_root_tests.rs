//! Two actual Root processes and two credential-separated daemon processes.
//! Only factory custody/registry recovery is exercised. Request/material data
//! are synthetic; this does not execute Training, Evaluation or a Model owner.

use super::BoundFactory;
use super::serve_optional_until;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_service::OriginalDerivedLearningMode;
use crate::authority_host_service::q24_model::FactoryRecord;
use crate::authority_host_service::q24_model::LiveFactoryProfile;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command as ProcessCommand;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_q24_model_cold_child_tests.rs"]
mod consumer;
#[path = "authority_host_q24_model_cold_fixture_tests.rs"]
mod fixture;
#[path = "authority_host_q24_model_cold_phase_tests.rs"]
mod phase;
#[path = "authority_host_learning_service_root_support.rs"]
mod support;

const CHILD_TEST: &str = "authority_host_runtime::session::q24_model::cold_root_tests::consumer::root_q24_factory_v2_dedicated_uid_child";
const ROOT_TEST: &str = "authority_host_runtime::session::q24_model::cold_root_tests::phase::root_q24_factory_v2_dedicated_root_phase";
const OWNER: &str = "root-q24-model-proposal-factory-v2";
const DIRECTORY: &str = "q24-model-proposal-factory-v2";
const WITNESS: &str = "q24-model-proposal-factory-v2.witness";
const UPDATE_RULE: &[u8] = b"root-q24-factory-service-cell-update-rule-v2";
const MATERIAL: &[u8] = b"synthetic-registry-control-not-a-model-proposal";

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct PhaseReceipt {
    phase: String,
    root_pid: u32,
    root_start: u64,
    daemon_pid: u32,
    daemon_start: u64,
    spawn_generation: u64,
    writer_proof: String,
    live: LiveFactoryProfile,
    record: FactoryRecord,
    missing_witness_refused: bool,
}

#[test]
#[ignore = "explicit actual Root, two protected bind domains and dedicated UID"]
fn root_q24_factory_v2_cold_reopens_original_files_with_new_root_and_writer() -> anyhow::Result<()>
{
    exercise_cold_recovery("reopen")
}

#[test]
#[ignore = "explicit actual Root, successful cold baseline before missing witness"]
fn root_q24_factory_v2_cold_missing_witness_never_reinitializes() -> anyhow::Result<()> {
    exercise_cold_recovery("reopen-then-missing")
}

fn exercise_cold_recovery(second_phase: &str) -> anyhow::Result<()> {
    // SAFETY: these calls only inspect the actual process credentials.
    assert_eq!(
        (unsafe { libc::getuid() }, unsafe { libc::geteuid() }),
        (0, 0)
    );
    let fixture = fixture::Fixture::new()?;
    let first = run_root_phase(fixture.protected.path(), "reserve")?;
    let setup: fixture::Setup = crate::authority_host_runtime::read_root_json(
        &fixture.protected.path().join("setup.json"),
    )?;
    let registry = setup.config.state_dir.join(DIRECTORY);
    let retained = support::protected_files(&registry)?;
    let witness_path = fixture.witnesses.path().join(WITNESS);
    let witness = std::fs::read(&witness_path)?;
    anyhow::ensure!(!witness.is_empty());
    let first_config: HostAuthorityServiceConfig = crate::authority_host_runtime::read_root_json(
        &fixture.protected.path().join("service-reserve.json"),
    )?;
    let expiry = first_config
        .writer
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("actual first writer required"))?
        .authority_lease
        .expires_at_unix_ms;
    let wait_end = Instant::now() + Duration::from_secs(6);
    while fixture::now_ms()? < expiry {
        anyhow::ensure!(
            Instant::now() < wait_end,
            "original writer retirement deadline"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    let second = run_root_phase(fixture.protected.path(), second_phase)?;
    assert_ne!(first.root_pid, second.root_pid);
    assert_ne!(first.daemon_pid, second.daemon_pid);
    assert_ne!(first.writer_proof, second.writer_proof);
    assert_ne!(first.live, second.live);
    assert_eq!(first.record, second.record);
    assert_eq!(first.live.reserved(), second.live.reserved());
    assert_eq!(
        first.spawn_generation.checked_add(1),
        Some(second.spawn_generation)
    );
    assert_eq!(
        second
            .live
            .witness_generation(second.spawn_generation)?
            .get(),
        first.spawn_generation,
    );
    assert_eq!(support::protected_files(&registry)?, retained);
    if second_phase == "reopen" {
        assert!(!second.missing_witness_refused);
        assert_eq!(std::fs::read(&witness_path)?, witness);
    } else {
        assert!(second.missing_witness_refused);
        assert!(!witness_path.exists());
    }
    println!(
        "ROOT_FACTORY_V2_COLD phase={second_phase} roots={},{} daemons={},{} original_generation={} current_generation={} registry_epoch=2 model_owner_created=false ordinary_chain=false",
        first.root_pid,
        second.root_pid,
        first.daemon_pid,
        second.daemon_pid,
        first.spawn_generation,
        second.spawn_generation,
    );
    Ok(())
}

struct RootProcess(Option<Child>);

impl Drop for RootProcess {
    fn drop(&mut self) {
        if let Some(child) = &mut self.0 {
            if !matches!(child.try_wait(), Ok(Some(_))) {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

fn run_root_phase(directory: &Path, phase: &str) -> anyhow::Result<PhaseReceipt> {
    let mut child = RootProcess(Some(
        ProcessCommand::new(std::env::current_exe()?)
            .args([
                "--exact",
                ROOT_TEST,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HEPTA_FACTORY_V2_ROOT_PHASE", phase)
            .env("HEPTA_FACTORY_V2_ROOT_DIRECTORY", directory)
            .current_dir("/")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?,
    ));
    let pid = child
        .0
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("Root child required"))?
        .id();
    let pin = support::pidfd(pid)?;
    let start = support::start_ticks(pid)?;
    let end = Instant::now() + Duration::from_secs(12);
    while child
        .0
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("Root child required"))?
        .try_wait()?
        .is_none()
    {
        anyhow::ensure!(Instant::now() < end, "actual Root child deadline");
        std::thread::sleep(Duration::from_millis(5));
    }
    let output = child
        .0
        .take()
        .ok_or_else(|| anyhow::anyhow!("Root result required"))?
        .wait_with_output()?;
    anyhow::ensure!(
        output.status.success(),
        "Root phase {phase}: {}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8(output.stdout)?;
    anyhow::ensure!(
        stdout.contains(&format!("ROOT_FACTORY_V2_PHASE phase={phase} pid={pid} ")),
        "missing exact Root phase receipt: {stdout}"
    );
    anyhow::ensure!(Instant::now() < end);
    anyhow::ensure!(crate::authority_host_runtime::owner_alive(&pin, end).is_err());
    let receipt: PhaseReceipt = crate::authority_host_runtime::read_root_json(
        &directory.join(format!("receipt-{phase}.json")),
    )?;
    assert_eq!(
        (&receipt.phase, receipt.root_pid, receipt.root_start),
        (&phase.to_owned(), pid, start)
    );
    println!("{stdout}");
    Ok(receipt)
}
