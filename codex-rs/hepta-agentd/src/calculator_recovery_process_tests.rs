use super::*;
use std::os::unix::fs::PermissionsExt;

fn launch(directory: &std::path::Path) -> io::Result<AgentdCalculatorPreviousRecoveryLaunch> {
    // Actual host ELF only checks executable custody; it is never started
    // as a Calculator helper and cannot supply an application receipt.
    let helper = directory.join("helper");
    let bytes = std::fs::read("/bin/true")?;
    std::fs::write(&helper, &bytes)?;
    std::fs::set_permissions(&helper, std::fs::Permissions::from_mode(0o700))?;
    Ok(AgentdCalculatorPreviousRecoveryLaunch {
        helper,
        helper_sha256: Sha256Digest::for_bytes(&bytes),
        state_directory: directory.to_owned(),
        previous_target: CalculatorTargetIdentity {
            session_instance: "1".repeat(32),
            task_id: 1,
            incarnation: "2".repeat(32),
        },
        operation_id: "source-operation".into(),
    })
}

#[test]
fn calculator_recovery_process_rejects_unsafe_or_mismatched_executable_before_start()
-> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let mut selected = launch(directory.path())?;
    selected.helper_sha256 = Sha256Digest::for_bytes(b"different executable");
    assert!(ProcessRecoveryChannel::prepare(selected).is_err());
    let selected = launch(directory.path())?;
    std::fs::set_permissions(&selected.helper, std::fs::Permissions::from_mode(0o777))?;
    assert!(ProcessRecoveryChannel::prepare(selected).is_err());
    let mut selected = launch(directory.path())?;
    let link = directory.path().join("linked-helper");
    std::os::unix::fs::symlink(&selected.helper, &link)?;
    selected.helper = link;
    assert!(ProcessRecoveryChannel::prepare(selected).is_err());
    Ok(())
}

#[test]
fn calculator_recovery_process_seals_bytes_and_refuses_effect_or_foreign_operation_without_spawn()
-> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let selected = launch(directory.path())?;
    let target = selected.previous_target.clone();
    let path = selected.helper.clone();
    let channel = ProcessRecoveryChannel::prepare(selected)?;
    std::fs::write(path, b"path changed after verification")?;
    // SAFETY: the descriptor belongs to the retained sealed executable.
    let seals = unsafe { libc::fcntl(channel.executable.as_raw_fd(), libc::F_GET_SEALS) };
    assert_eq!(seals & libc::F_SEAL_WRITE, libc::F_SEAL_WRITE);
    for (action, operation) in [
        ("evaluate", "source-operation"),
        ("observe", "foreign-operation"),
        ("read_calculator", "source-operation"),
    ] {
        let request = serde_json::to_vec(
            &serde_json::json!({"schema_version":1,"action":action,"target":target,"operation_id":operation}),
        )?;
        assert!(channel.exchange(&request).is_err());
    }
    assert_eq!(channel.state.lock().expect("helper state").starts, 0);
    Ok(())
}
