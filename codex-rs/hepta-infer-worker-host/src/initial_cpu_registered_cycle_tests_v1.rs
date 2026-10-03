//! The finite registered purpose cannot enter either old parser or weaken roles.
use super::*;

fn config(observer: bool) -> HostResult<RegisteredSelfIterationOwnerConfigurationV1> {
    let pin = Digest32::of_bytes(b"public independent source").to_string();
    let source = serde_json::json!({"path":"/fixture/root/public", "digest":pin});
    Ok(serde_json::from_value(serde_json::json!({
        "schema":"hepta.cpu-neuron.registered-self-iteration-owner.v1",
        "purpose":if observer {"canary-observation"} else {"cycle-selection"},
        "program":source,"actor":{"id":"original-independent-role","uid":0,"gid":0,
            "public_key_hex":"00".repeat(32),"credential_digest":pin,"private_key_path":"/fixture/role/key"},
        "learning_trust":source,"canonical_envelope_digest":pin,
        "consumer":{"path":"/fixture/G/consumer","uid":1},
        "evaluation":{"path":"/fixture/E/evaluation","uid":2},
        "candidates":[{"candidate_id":"original-candidate","successor":{"configuration":source,"selection":source},"rollback":{"configuration":source,"selection":source}}],
        "inaccessible_paths":if observer {Vec::<&str>::new()} else {vec!["/fixture/private/a","/fixture/private/b","/fixture/private/c","/fixture/private/d","/fixture/private/e"]},
        "observer_custody":if observer {serde_json::json!({"trust_configuration":source,"cycle_approval":null})} else {Value::Null},
        "selection":if observer {source.clone()} else {Value::Null},
        "canary":if observer {source} else {Value::Null},
    }))?)
}
#[test]
fn old_or_shared_role_configuration_cannot_enter_registered_purpose() -> HostResult<()> {
    validate_purpose(&config(false)?, false)?;
    validate_purpose(&config(true)?, true)?;
    for change in 0..11 {
        let mut changed = config(false)?;
        match change {
            0 => changed.schema = "hepta.cpu-neuron.self-iteration-selection.v1".into(),
            1 => changed.purpose = "canary-observation".into(),
            2 => changed.actor.uid = 3,
            3 => changed.actor.gid = 3,
            4 => changed.consumer.uid = 0,
            5 => changed.evaluation.uid = changed.consumer.uid,
            6 => {
                changed.inaccessible_paths.pop();
            }
            7 => changed.candidates.clear(),
            8 => changed.candidates.push(changed.candidates[0].clone()),
            9 => changed.selection = Some(changed.program.clone()),
            10 => changed.observer_custody = config(true)?.observer_custody,
            _ => unreachable!(),
        }
        assert!(
            validate_purpose(&changed, false).is_err(),
            "change {change}"
        );
    }
    let mut observer = config(true)?;
    observer.canary = None;
    assert!(validate_purpose(&observer, true).is_err());
    Ok(())
}
#[test]
fn bounded_evidence_identity_binds_each_full_original_fact_and_role() -> HostResult<()> {
    let pins = ["round", "frozen", "evaluation", "physical-payload"]
        .map(|s| Digest32::of_bytes(s.as_bytes()));
    let original = evidence_identity("cycle-selection", pins[0], pins[1], pins[2], pins[3]);
    assert_eq!(
        id(&format!("cpu.registered.cycle.{original}"))?
            .as_str()
            .len(),
        85
    );
    assert_ne!(
        original,
        evidence_identity("canary-observation", pins[0], pins[1], pins[2], pins[3])
    );
    for index in 0..4 {
        let mut changed = pins;
        changed[index] = Digest32::of_bytes(b"different original fact");
        assert_ne!(
            original,
            evidence_identity(
                "cycle-selection",
                changed[0],
                changed[1],
                changed[2],
                changed[3]
            )
        );
    }
    Ok(())
}

#[test]
#[ignore = "actual UID0 filesystem boundary; run original ELF without loading role seeds"]
fn actual_root_new_public_artifact_records_reuse_original_visibility() -> HostResult<()> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    if rustix::process::getuid().as_raw() != 0 {
        return Err("actual Root required".into());
    }
    let temp = tempfile::tempdir_in("/run")?;
    let root = temp.path().canonicalize()?;
    let names = [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ];
    for name in names {
        let path = root.join(name);
        std::fs::create_dir(&path)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))?;
        if name != "writer" {
            let file = path.join("actual-new-public-record");
            std::fs::write(&file, b"original immutable record")?;
            std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o600))?;
        }
    }
    let private = root.join("private-original-owner-state");
    std::fs::create_dir(&private)?;
    std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o700))?;
    let private_file = private.join("private-lease");
    std::fs::write(&private_file, b"private retained issuance")?;
    std::fs::set_permissions(&private_file, std::fs::Permissions::from_mode(0o600))?;
    publication::expose_original_public_artifacts(&root)?;
    publication::expose_original_public_artifacts(&root)?;
    for name in names {
        assert_eq!(std::fs::metadata(root.join(name))?.mode() & 0o777, 0o755);
        if name != "writer" {
            assert_eq!(
                std::fs::metadata(root.join(name).join("actual-new-public-record"))?.mode() & 0o777,
                0o644
            );
        }
    }
    assert_eq!(std::fs::metadata(&private)?.mode() & 0o777, 0o700);
    assert_eq!(std::fs::metadata(&private_file)?.mode() & 0o777, 0o600);
    let link = root.join("payloads/substituted-record");
    std::os::unix::fs::symlink(&private_file, &link)?;
    assert!(publication::expose_original_public_artifacts(&root).is_err());
    assert_eq!(std::fs::metadata(private_file)?.mode() & 0o777, 0o600);
    Ok(())
}
