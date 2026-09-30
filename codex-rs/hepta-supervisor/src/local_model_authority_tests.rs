use super::*;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SystemAuthorityClock;

fn config() -> Config {
    Config {
        schema_version: 1,
        signer_id: "ordinary-model-owner".into(),
        key_file: "/var/lib/hepta-model/key".into(),
        issuer_socket: "/run/hepta-model/issuer".into(),
        process_identity_file: "/run/hepta-model/identity.json".into(),
        socket_gid: 1000,
        workload_uid: 1000,
        state_directory: "/var/lib/hepta-model/state".into(),
        trust_directory: "/var/lib/hepta-model-trust".into(),
        revocations_file: "/var/lib/hepta-model/revocations.json".into(),
        cgroup_root: "/sys/fs/cgroup/hepta-model-test".into(),
        fleet_database: "/var/lib/hepta-model/fleet/state/fleet-resources.sqlite3".into(),
        allowed_subject_ids: BTreeSet::from(["00000000-0000-4000-8000-000000000001".into()]),
        allowed_executable_sha256: BTreeSet::from(["a".repeat(64)]),
        allowed_executable_paths: BTreeSet::from(["/usr/bin/sleep".into()]),
        grant_lifetime_ms: 30_000,
        request_timeout_ms: 2_000,
    }
}

fn cgroup(subject: &str, kind: &str) -> String {
    format!("0::/hepta-model-test/agent-{subject}/{kind}-00000000-0000-4000-8000-000000000002")
}

#[test]
fn enrollment_uses_exact_kernel_cgroup_and_main_execution() -> anyhow::Result<()> {
    let config = config();
    config.validate()?;
    let subject = config
        .allowed_subject_ids
        .first()
        .context("missing test subject")?;
    let group = cgroup(subject, "main");
    assert_eq!(config.admitted_subject(1000, &group)?, *subject);
    for rejected in [
        cgroup(subject, "matrix"),
        cgroup("00000000-0000-4000-8000-000000000003", "main"),
        format!("{group}/nested"),
        format!("{group}\n0::/forged"),
        group.replace("hepta-model-test/", "hepta-model-test-evil/"),
    ] {
        assert!(config.admitted_subject(1000, &rejected).is_err());
    }
    assert!(config.admitted_subject(0, &group).is_err());
    assert!(config.admitted_subject(1001, &group).is_err());
    Ok(())
}

#[test]
fn policy_rejects_root_workloads_and_shared_replaceable_trust() {
    let mut candidate = config();
    candidate.workload_uid = 0;
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate.trust_directory = candidate.state_directory.join("frontier");
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate.allowed_executable_sha256.insert("0".repeat(64));
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate.cgroup_root = "/sys/fs/cgroup/hepta/../other".into();
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate.allowed_executable_paths.clear();
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate
        .allowed_executable_paths
        .insert("relative/program".into());
    assert!(candidate.validate().is_err());
    let mut candidate = config();
    candidate.allowed_executable_paths = (0..=MAX_ENROLLED_EXECUTABLES)
        .map(|index| PathBuf::from(format!("/immutable/program-{index}")))
        .collect();
    assert!(candidate.validate().is_err());
}

#[test]
fn actual_signed_ordinary_grant_is_exact_one_use_and_cannot_change_destination()
-> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let signer = SigningKey::from_bytes(&[7; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "ordinary-model-owner".into(),
        signer.verifying_key().to_bytes(),
        head.clone(),
    )?;
    let subject = "00000000-0000-4000-8000-000000000001".to_string();
    let peer = Peer {
        pid: 1,
        start_ticks: 1,
        subject: subject.clone(),
        cgroup: cgroup(&subject, "main"),
        cgroup_device: 1,
        cgroup_inode: 1,
        executable_sha256: "a".repeat(64),
    };
    let config = config();
    let clock = SystemAuthorityClock;
    let binding = FinalUseBinding {
        subject_id: subject,
        destination_id: "codex-app-server:42".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let request = || ModelIssuerRequest {
        schema_version: MODEL_ISSUER_SCHEMA_VERSION,
        operation: MODEL_ISSUER_OPERATION.into(),
        binding: binding.clone(),
    };
    let signed = Issuer::sign(&config, &signer, &clock, request(), &peer, &head)?;
    authority.claim(&signed, &binding)?.enter(&binding)?;
    assert!(authority.claim(&signed, &binding).is_err());
    let mut other = request();
    other.binding.destination_id = "self-iteration.acceptance".into();
    assert!(Issuer::sign(&config, &signer, &clock, other, &peer, &head).is_err());
    for destination in [
        "provider:codex-app-server",
        "codex-app-server:0",
        "codex-app-server:042",
        "codex-app-server:+42",
        "codex-app-server:42/other",
    ] {
        let mut other = request();
        other.binding.destination_id = destination.into();
        assert!(Issuer::sign(&config, &signer, &clock, other, &peer, &head).is_err());
    }
    let mut other = request();
    other.binding.subject_id = "different-agent".into();
    assert!(Issuer::sign(&config, &signer, &clock, other, &peer, &head).is_err());
    let mut other = request();
    other.operation = "self-iteration.acceptance".into();
    assert!(Issuer::sign(&config, &signer, &clock, other, &peer, &head).is_err());
    let mut other = request();
    other.binding.payload_sha256 = [0; 32];
    assert!(Issuer::sign(&config, &signer, &clock, other, &peer, &head).is_err());
    assert_ne!(
        signed.grant.nonce,
        Issuer::sign(&config, &signer, &clock, request(), &peer, &head)?
            .grant
            .nonce
    );
    Ok(())
}
