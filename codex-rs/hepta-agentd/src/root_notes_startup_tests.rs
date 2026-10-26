use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;

fn profile() -> serde_json::Value {
    let digest = Digest32::of_bytes(b"root profile fixture; not a human authority").to_string();
    serde_json::json!({
        "schema": "hepta.root.notes_launch_profile.v1",
        "grant_lifetime_ms": 1000,
        "bindings": {
            "principal_scope": "fixture.notes.scope",
            "principal_scope_digest": digest,
            "issuer_id": "issuer:fixture",
            "policy_generation": 1,
            "locale": "zh-CN",
            "runtime_body_digest": digest,
            "preference_state_digest": digest,
            "model_tuple_digest": digest,
            "prompt_registry_digest": digest,
            "artifact_set_digest": digest,
        }
    })
}

fn model_route(profile: &serde_json::Value) -> serde_json::Value {
    serde_json::json!({
        "thread_id": "registered-original-thread",
        "app_server_session_id": "registered-original-session",
        "principal_scope_digest": profile["bindings"]["principal_scope_digest"],
        "registered_tool_schema_sha256": Digest32::of_bytes(
            crate::AgentdNotesModelRoute::TOOL_DEFINITION_JSON.as_bytes()
        ).to_string(),
    })
}

#[test]
fn root_profile_preserves_the_supplied_model_route_and_keeps_legacy_route_absent()
-> anyhow::Result<()> {
    let mut input = profile();
    for missing in [true, false] {
        if !missing {
            input["model_route"] = serde_json::Value::Null;
        }
        let original: Profile = serde_json::from_value(input.clone())?;
        validate_profile(&original, "issuer:fixture")?;
        assert!(original.model_route.is_none());
    }
    let declared = model_route(&input);
    input["model_route"] = declared.clone();
    let original: Profile = serde_json::from_value(input)?;
    validate_profile(&original, "issuer:fixture")?;
    // The original producer serializes this exact DTO into its sealed file.
    // Serialization must preserve supplied bindings, never fill missing ones
    // from the expected schema constant or from transport discovery.
    assert_eq!(serde_json::to_value(original.model_route)?, declared);
    Ok(())
}

#[test]
fn root_profile_refuses_model_routes_before_notes_policy_registration() -> anyhow::Result<()> {
    let mut input = profile();
    input["model_route"] = model_route(&input);
    for (field, value) in [
        ("thread_id", serde_json::json!("")),
        (
            "app_server_session_id",
            serde_json::json!("wrong session\n"),
        ),
        (
            "principal_scope_digest",
            serde_json::json!(Digest32::of_bytes(b"another human scope").to_string()),
        ),
        (
            "registered_tool_schema_sha256",
            serde_json::json!(Digest32::of_bytes(b"another registered definition").to_string()),
        ),
    ] {
        let mut changed = input.clone();
        changed["model_route"][field] = value;
        let original: Profile = serde_json::from_value(changed)?;
        assert!(validate_profile(&original, "issuer:fixture").is_err());
    }
    let mut missing = input.clone();
    missing["model_route"]
        .as_object_mut()
        .unwrap()
        .remove("registered_tool_schema_sha256");
    assert!(serde_json::from_value::<Profile>(missing).is_err());
    for field in [
        "agent_id",
        "issuer_id",
        "control_socket",
        "codex_home",
        "target",
    ] {
        let mut changed = input.clone();
        changed["model_route"][field] = serde_json::json!("untrusted override");
        assert!(serde_json::from_value::<Profile>(changed).is_err());
    }
    // Decode the raw file, not an already collapsed JSON Value: a duplicated
    // route key must not select one of two different declared original threads.
    let bytes = serde_json::to_string(&input)?.replacen(
        "\"thread_id\":\"registered-original-thread\"",
        "\"thread_id\":\"registered-original-thread\",\"thread_id\":\"replacement\"",
        /*count*/ 1,
    );
    assert!(serde_json::from_str::<Profile>(&bytes).is_err());
    Ok(())
}

#[test]
fn ordinary_file_cannot_be_a_pending_root_deployment() {
    assert!(validate_empty_deployment(&tempfile::tempfile().unwrap()).is_err());
}

#[test]
fn root_profile_requires_the_exact_bounded_policy_predecessor() -> anyhow::Result<()> {
    let mut input = profile();
    let legacy: Profile = serde_json::from_value(input.clone())?;
    validate_profile(&legacy, "issuer:fixture")?;
    assert_eq!(legacy.expected_notes_policy, None);
    input["expected_notes_policy"] = serde_json::json!({
        "target": {
            "session_instance": "1".repeat(32), "task_id": 1, "incarnation": "2".repeat(32),
        },
        "lifetime_ms": 1000,
    });
    let declared: Profile = serde_json::from_value(input.clone())?;
    validate_profile(&declared, "issuer:fixture")?;
    assert_eq!(
        declared.expected_notes_policy,
        Some(ExpectedNotesPolicy {
            target: NotesTargetIdentity {
                session_instance: "1".repeat(32),
                task_id: 1,
                incarnation: "2".repeat(32),
            },
            lifetime_ms: 1000,
        })
    );
    for (old, next) in [(0, 1000), (300_001, 1000), (1000, 0), (1000, 1001)] {
        let mut changed = input.clone();
        changed["expected_notes_policy"]["lifetime_ms"] = serde_json::json!(old);
        changed["grant_lifetime_ms"] = serde_json::json!(next);
        let declared: Profile = serde_json::from_value(changed)?;
        assert!(validate_profile(&declared, "issuer:fixture").is_err());
    }
    for (field, value) in [
        (
            "session_instance",
            serde_json::json!("unregistered-session"),
        ),
        ("task_id", serde_json::json!(0)),
        ("incarnation", serde_json::json!("0".repeat(31))),
    ] {
        let mut changed = input.clone();
        changed["expected_notes_policy"]["target"][field] = value;
        let declared: Profile = serde_json::from_value(changed)?;
        assert!(validate_profile(&declared, "issuer:fixture").is_err());
    }
    for field in [
        "subject_id",
        "signer_id",
        "successor",
        "scope_sha256",
        "grant",
    ] {
        let mut changed = input.clone();
        changed["expected_notes_policy"][field] = serde_json::json!("override");
        assert!(serde_json::from_value::<Profile>(changed).is_err());
    }
    input["expected_notes_policy"]
        .as_object_mut()
        .unwrap()
        .remove("lifetime_ms");
    assert!(serde_json::from_value::<Profile>(input).is_err());
    let duplicate = serde_json::to_string(&profile())?.replacen(
        "\"grant_lifetime_ms\":1000",
        "\"expected_notes_policy\":null,\"expected_notes_policy\":null,\"grant_lifetime_ms\":1000",
        /*count*/ 1,
    );
    assert!(serde_json::from_str::<Profile>(&duplicate).is_err());
    Ok(())
}

#[test]
#[ignore = "requires actual Root; execute the user-built test ELF in the isolated Root runner"]
fn original_root_seals_only_empty_private_deployment_and_readonly_consumer_observes_it() {
    // SAFETY: geteuid reads the current process's actual UID.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    // SAFETY: the static name is NUL terminated and success returns a new FD.
    let raw = unsafe {
        libc::memfd_create(
            c"hepta-notes-startup-test".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    assert!(raw >= 0);
    // SAFETY: this adopts exactly the fresh owned descriptor above.
    let file = unsafe { File::from_raw_fd(raw) };
    assert_eq!(unsafe { libc::fchmod(raw, 0o600) }, 0);
    let mut consumer = File::open(format!("/proc/self/fd/{raw}")).unwrap();
    assert!(
        validate_empty_deployment(&consumer).is_err(),
        "a read-only consumer cannot be a producer"
    );
    let producer = file.try_clone().unwrap();
    seal_deployment(producer, b"actual sealed payload").unwrap();
    crate::authority_host_bootstrap_seal::validate_sealed(&consumer, 21).unwrap();
    let mut actual = Vec::new();
    consumer.read_to_end(&mut actual).unwrap();
    assert_eq!(actual, b"actual sealed payload");
    assert!(
        seal_deployment(file, b"replacement").is_err(),
        "a previous sealed deployment is never reset"
    );
}
