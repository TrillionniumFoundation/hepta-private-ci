use super::*;
#[test]
fn unprotected_generator_config_is_rejected_before_role_or_key_use() {
    let path = std::env::temp_dir().join(format!("parameter-g-unprotected-{}", std::process::id()));
    std::fs::write(&path, b"{\"schema\":\"caller claimed G\"}").expect("public fixture");
    assert!(run_fixed_parameter_generator_v3(&path).is_err());
    assert_eq!(
        std::fs::read(&path).expect("unchanged"),
        b"{\"schema\":\"caller claimed G\"}"
    );
    std::fs::remove_file(path).expect("cleanup");
}

#[test]
fn complete_parameter_role_pins_have_bounded_distinct_evidence_ids() {
    let round = Digest32::of_bytes(b"actual sealed round");
    let payload = Digest32::of_bytes(b"whole original signed payload");
    let generator = parameter_role_evidence_id(LearningEvidenceRoleV1::Generator, round, payload)
        .expect("complete pins fit the original StableId bound");
    assert_eq!(generator.as_str().len(), "parameter-g.".len() + 64);
    assert_eq!(
        generator,
        parameter_role_evidence_id(LearningEvidenceRoleV1::Generator, round, payload)
            .expect("same exact operation")
    );
    for (role, other_round, other_payload) in [
        (LearningEvidenceRoleV1::Observer, round, payload),
        (
            LearningEvidenceRoleV1::Generator,
            Digest32::of_bytes(b"another round"),
            payload,
        ),
        (
            LearningEvidenceRoleV1::Generator,
            round,
            Digest32::of_bytes(b"another whole payload"),
        ),
    ] {
        let other = parameter_role_evidence_id(role, other_round, other_payload).expect("bounded");
        assert_eq!(other.as_str().len(), 76);
        assert_ne!(generator, other);
    }
    assert!(parameter_role_evidence_id(LearningEvidenceRoleV1::Evaluator, round, payload).is_err());
}

#[test]
fn parameter_generator_policy_preserves_distinct_enrolled_nonroot_group() -> Result<()> {
    let pin = Digest32::of_bytes(b"original complete pin").to_string();
    // Policy shape alone grants no authenticated G role. Original native trust,
    // actual process/group, controller, key, full Source pins and expiry still run.
    let trust = ReviewTrustWireV1 {
        root_id: "root".into(),
        root_verifying_key_hex: "00".repeat(32),
        root_valid_from: 1,
        root_expires_at: 100,
        distribution_id: "distribution".into(),
        generation: 1,
        effective_at: 1,
        issued_at: 1,
        expires_at: 100,
        scope_digest: pin.clone(),
        objective_digest: pin.clone(),
        authority_epoch: 1,
        signers: Vec::new(),
        signature_hex: "00".repeat(64),
    };
    let mut config = FixedParameterGeneratorConfigV3 {
        schema: "hepta.fixed-parameter-generator-config.v3".into(),
        uid: 986,
        gid: 975,
        program_digest: pin.clone(),
        private_key_path: "/role/private.key".into(),
        root_verifying_key_hex: trust.root_verifying_key_hex.clone(),
        source: ParameterRoleSourceV3 {
            path: "/root-pinned/source".into(),
            digest: pin.clone(),
        },
        scope_digest: pin.clone(),
        objective_digest: pin.clone(),
        distribution_generation: 1,
        authority_epoch: 1,
        inaccessible_paths: (0..5).map(|i| format!("/denied/{i}").into()).collect(),
    };
    let inputs = FixedParameterGeneratorInputsV3 {
        schema: "hepta.fixed-parameter-generator-inputs.v3".into(),
        trust,
        profile: ParameterRoleSourceV3 {
            path: "/root-pinned/profile".into(),
            digest: pin.clone(),
        },
        baseline_material: ParameterRoleSourceV3 {
            path: "/root-pinned/material".into(),
            digest: pin.clone(),
        },
        round_digest: pin.clone(),
        canonical_policy_digest: pin,
        admitted_at_ms: 2,
        deadline_ms: 90,
    };
    validate_policy(&config, &inputs, 30)?;
    config.gid = 0;
    assert!(validate_policy(&config, &inputs, 30).is_err());
    config.gid = 975;
    config.uid = 0;
    assert!(validate_policy(&config, &inputs, 30).is_err());
    config.uid = 986;
    config.scope_digest = Digest32::of_bytes(b"changed independently pinned scope").to_string();
    assert!(validate_policy(&config, &inputs, 30).is_err());
    Ok(())
}

#[test]
#[ignore = "requires actual Root bounded systemd service and nonroot UID986/GID975 child"]
fn actual_root_generator_preserves_enrolled_group_at_process_boundary() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    const CHILD: &str = "HEPTA_ACTUAL_GENERATOR_GROUP_CHILD";
    if std::env::var_os(CHILD).is_some() {
        boundary_in_service(986, 975, "hepta-native-generator-")?;
        assert!(boundary_in_service(987, 975, "hepta-native-generator-").is_err());
        assert!(boundary_in_service(986, 976, "hepta-native-generator-").is_err());
        assert!(boundary_in_service(0, 975, "hepta-native-generator-").is_err());
        assert!(boundary_in_service(986, 0, "hepta-native-generator-").is_err());
        return Ok(());
    }
    let actual_status = std::fs::read_to_string("/proc/self/status")?;
    if actual_status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .is_none_or(|values| {
            values.split_whitespace().count() != 4
                || values.split_whitespace().any(|value| value != "0")
        })
    {
        return Err("requires actual Root".into());
    }
    struct OriginalFixtureDirectory(PathBuf);
    impl Drop for OriginalFixtureDirectory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let root = OriginalFixtureDirectory(PathBuf::from(format!(
        "/run/hepta-g-group-{}-{stamp}",
        std::process::id()
    )));
    std::fs::create_dir(&root.0)?;
    std::fs::set_permissions(&root.0, std::fs::Permissions::from_mode(0o755))?;
    let program = root.0.join("original-test-elf");
    std::fs::copy(std::env::current_exe()?, &program)?;
    std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o555))?;
    let unit = format!("hepta-native-generator-group-smoke-{}", std::process::id());
    let status = std::process::Command::new("/usr/bin/systemd-run")
        .args(["--quiet", "--wait", "--pipe", "--collect", "--setenv=HEPTA_ACTUAL_GENERATOR_GROUP_CHILD=1"]).arg(format!("--unit={unit}"))
        .args(["--property=NoNewPrivileges=yes", "--property=CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_SETPCAP", "--property=AmbientCapabilities=", "--property=MemoryMax=268435456", "--property=TasksMax=16", "--property=CPUQuota=100%", "--property=RuntimeMaxSec=30", "--property=ProtectSystem=strict"])
        .arg("/usr/bin/setpriv")
        .args(["--reuid=986", "--regid=975", "--clear-groups", "--no-new-privs", "--inh-caps=-all", "--bounding-set=-all", "--ambient-caps=-all"])
        .arg(&program).args(["--ignored", "--exact", "fixed_parameter_generator_v3::tests::actual_root_generator_preserves_enrolled_group_at_process_boundary", "--nocapture"])
        .status()?;
    assert!(
        status.success(),
        "actual independent original Group boundary"
    );
    Ok(())
}
