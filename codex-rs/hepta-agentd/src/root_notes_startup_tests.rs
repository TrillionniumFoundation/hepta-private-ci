use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;

#[test]
fn ordinary_file_cannot_be_a_pending_root_deployment() {
    assert!(validate_empty_deployment(&tempfile::tempfile().unwrap()).is_err());
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

fn recovery_profile(previous: Option<NotesTargetIdentity>) -> Profile {
    serde_json::from_value(serde_json::json!({
        "schema":"hepta.root.notes_launch_profile.v1", "grant_lifetime_ms":1000,
        "bindings":{"principal_scope":"test.read-only-contract","principal_scope_digest":"11".repeat(32),
            "issuer_id":"test-contract","policy_generation":1,"locale":"zh-CN",
            "runtime_body_digest":"22".repeat(32),"preference_state_digest":"33".repeat(32),
            "model_tuple_digest":"44".repeat(32),"prompt_registry_digest":"55".repeat(32),
            "artifact_set_digest":"66".repeat(32)},
        "previous_recovery":previous.map(|target| serde_json::json!({"helper":"/unused-helper",
            "helper_sha256":"77".repeat(32),"state_directory":"/unused-store",
            "previous_target":target,"operation_id":"original-old-operation"}))
    })).unwrap()
}

#[test]
fn successor_policy_contract_requires_the_exact_old_identity_and_distinct_reserved_target() {
    let old = NotesTargetIdentity {
        session_instance: "a".repeat(32),
        task_id: 1,
        incarnation: "b".repeat(32),
    };
    let next = NotesTargetIdentity {
        session_instance: "c".repeat(32),
        task_id: 1,
        incarnation: "d".repeat(32),
    };
    let profile = recovery_profile(Some(old.clone()));
    let prior = RootNotesPolicyPredecessor {
        target: &old,
        grant_lifetime_ms: 1000,
    };
    assert!(validate_recovery_policy(&profile, &prior, &next).is_ok());
    assert!(validate_recovery_policy(&profile, &prior, &old).is_err());
    assert!(
        validate_recovery_policy(
            &profile,
            &RootNotesPolicyPredecessor {
                target: &next,
                grant_lifetime_ms: 1000
            },
            &old
        )
        .is_err()
    );
}

#[test]
fn successor_policy_contract_cannot_drop_the_old_recovery_or_invent_a_policy_lifetime() {
    let old = NotesTargetIdentity {
        session_instance: "a".repeat(32),
        task_id: 1,
        incarnation: "b".repeat(32),
    };
    let next = NotesTargetIdentity {
        session_instance: "c".repeat(32),
        task_id: 1,
        incarnation: "d".repeat(32),
    };
    assert!(
        validate_recovery_policy(
            &recovery_profile(None),
            &RootNotesPolicyPredecessor {
                target: &old,
                grant_lifetime_ms: 1000
            },
            &next
        )
        .is_err()
    );
    assert!(
        validate_recovery_policy(
            &recovery_profile(Some(old.clone())),
            &RootNotesPolicyPredecessor {
                target: &old,
                grant_lifetime_ms: 0
            },
            &next
        )
        .is_err()
    );
}
