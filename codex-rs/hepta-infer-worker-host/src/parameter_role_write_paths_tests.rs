use super::*;
use std::os::unix::fs::PermissionsExt;

fn request(purpose: ParameterRoleExecutionPurposeV1) -> ParameterRoleExecutionV1 {
    ParameterRoleExecutionV1 {
        purpose,
        program: ParameterRoleSourceV3 {
            path: "/nonexistent-program".into(),
            digest: Digest32::of_bytes(b"program").to_string(),
        },
        configuration: ParameterRoleSourceV3 {
            path: "/nonexistent-config".into(),
            digest: Digest32::of_bytes(b"configuration").to_string(),
        },
        uid: 0,
        gid: 0,
        original_effect_digest: Digest32::of_bytes(b"effect"),
        inaccessible_paths: Vec::new(),
    }
}

#[test]
fn readonly_finite_purposes_cannot_echo_caller_write_paths() -> HostResult<()> {
    for purpose in [
        ParameterRoleExecutionPurposeV1::ObserverPairedAdmission,
        ParameterRoleExecutionPurposeV1::GeneratorProfile,
        ParameterRoleExecutionPurposeV1::EvaluatorPairedReview,
        ParameterRoleExecutionPurposeV1::EvaluatorPreRegistration,
        ParameterRoleExecutionPurposeV1::SelectorRegisteredCycleStage,
        ParameterRoleExecutionPurposeV1::ObserverRegisteredCanary,
    ] {
        assert!(
            derive(
                &request(purpose),
                br#"{"work_directory":"/","ReadWritePaths":"/"}"#
            )?
            .is_empty()
        );
    }
    Ok(())
}

#[test]
fn unknown_or_partial_original_writer_config_is_rejected() {
    assert!(
        derive(
            &request(ParameterRoleExecutionPurposeV1::ObserverPairedExecution),
            br#"{"work_directory":"/"}"#
        )
        .is_err()
    );
    assert!(
        derive(
            &request(ParameterRoleExecutionPurposeV1::ObserverPairedFinish),
            br#"{"schema":"hepta.fixed-paired-custody-finish-config.v1","evidence_path":"/"}"#
        )
        .is_err()
    );
    assert!(
        derive(
            &request(ParameterRoleExecutionPurposeV1::ArtifactPreRegistrationPublication),
            br#"{"schema":"wrong","owner_root":"/"}"#
        )
        .is_err()
    );
}

#[test]
#[ignore = "requires actual Root original protected paths and strict systemd mount namespace"]
fn actual_root_strict_namespace_writes_only_original_cas_and_sink_paths() -> HostResult<()> {
    require_root_caller()?;
    let root = tempfile::Builder::new()
        .prefix("hepta-purpose-writes-")
        .tempdir_in("/run")?;
    let paths = ["cas", "evidence", "ack", "denied"];
    for name in paths {
        let path = root.path().join(name);
        std::fs::create_dir(&path)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))?;
    }
    let cas = root.path().join("cas/holdout-cas.bin");
    std::fs::write(&cas, b"original")?;
    std::fs::set_permissions(&cas, std::fs::Permissions::from_mode(0o600))?;
    let source = serde_json::json!({"path":"/readonly/original","digest":Digest32::of_bytes(b"readonly").to_string()});
    let config = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.fixed-paired-custody-finish-config.v1", "program_digest":Digest32::of_bytes(b"program").to_string(),
        "root_verifying_key_hex":"00", "execution":source, "evaluator_result":source,
        "private_directory":root.path().join("cas"), "witness_path":root.path().join("witness"),
        "evidence_path":root.path().join("evidence/full.bin"), "ack_path":root.path().join("ack/ack.bin")
    }))?;
    let writable = derive(
        &request(ParameterRoleExecutionPurposeV1::ObserverPairedFinish),
        &config,
    )?;
    assert!(writable.contains(&cas));
    assert!(!writable.contains(&root.path().join("cas")));
    assert!(!writable.contains(&root.path().join("denied")));
    let mut denied_request = request(ParameterRoleExecutionPurposeV1::ObserverPairedFinish);
    denied_request.inaccessible_paths = vec![cas.clone()];
    assert!(derive(&denied_request, &config).is_err());
    let unit = format!("hepta-purpose-write-smoke-{}", std::process::id());
    let status = Command::new("/usr/bin/systemd-run")
        .args(["--quiet", "--wait", "--pipe", "--collect"])
        .arg(format!("--unit={unit}"))
        .args(["--property=ProtectSystem=strict", "--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=", "--property=AmbientCapabilities=", "--property=RuntimeMaxSec=20"])
        .arg(format!("--property=ReadWritePaths={}", writable.iter().map(|p| p.display().to_string()).collect::<Vec<_>>().join(" ")))
        .arg("/bin/sh").args(["-c", "set -eu; printf appended >> \"$1\"; printf full > \"$2\"; printf ack > \"$3\"; if printf denied > \"$4\"; then exit 9; fi; if printf denied > \"$5\"; then exit 10; fi", "original"])
        .arg(&cas).arg(root.path().join("evidence/full.bin")).arg(root.path().join("ack/ack.bin"))
        .arg(root.path().join("denied/foreign.bin")).arg(root.path().join("cas/foreign.bin"))
        .stdin(Stdio::null()).status()?;
    assert!(status.success(), "actual strict mount namespace");
    assert_eq!(std::fs::read(&cas)?, b"originalappended");
    assert_eq!(
        std::fs::read(root.path().join("evidence/full.bin"))?,
        b"full"
    );
    assert_eq!(std::fs::read(root.path().join("ack/ack.bin"))?, b"ack");
    assert!(!root.path().join("denied/foreign.bin").exists());
    assert!(!root.path().join("cas/foreign.bin").exists());
    Ok(())
}
