//! Real listener ordering only; no issuer, writer, model or human authority.
use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::net::UnixStream;

fn config(parent: &Path, gid: u32) -> HostAuthorityServiceConfig {
    HostAuthorityServiceConfig {
        schema_version: 1,
        state_dir: parent.join("unused-state"),
        required_bind: HostAuthorityBindIdentity {
            mountpoint: parent.join("unused-mount"),
            source_path: parent.join("unused-source"),
            device: 0,
            inode: 0,
        },
        signer_id: "unused-listener-test".into(),
        expected_verifying_key: [0; 32],
        lease_id: "unused-listener-test".into(),
        lease_revision: 1,
        writer: None,
        checkpoint_state_dir: None,
        consumers: None,
        sockets: crate::HostAuthoritySocketPaths {
            observation: parent.join("observation.sock"),
            issuer: parent.join("issuer.sock"),
            checkpoint: parent.join("checkpoint.sock"),
            device_frontier: Some(parent.join("device.sock")),
            notes_frontier: Some(parent.join("notes.sock")),
        },
        peer_uid: 60001,
        peer_gid: gid,
        timeout_ms: 500,
        lifetime_ms: 1000,
        issuer_record_profile: crate::HostIssuerRecordProfile::TextRecovery,
    }
}

#[test]
fn readiness_is_not_called_for_an_invalid_original_lane_parent() {
    let directory = tempfile::tempdir().unwrap();
    let config = config(directory.path(), /*gid*/ 60001);
    let mut called = false;
    let result = bind_runtime_lanes(&config, || {
        called = true;
        Ok(())
    });
    assert!(result.is_err());
    assert!(!called);
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0);
}

#[test]
#[ignore = "explicit actual Root listener qualification under /run; no authority or product launch"]
fn all_original_listeners_precede_the_one_shot_handoff_and_failure_cleans_up() {
    // SAFETY: these calls only read the actual qualification credentials.
    assert_eq!(unsafe { (libc::getuid(), libc::geteuid()) }, (0, 0));
    let directory = tempfile::Builder::new()
        .prefix("hepta-ready-")
        .tempdir_in("/run")
        .unwrap();
    let parent = directory.path().join("r");
    std::fs::create_dir(&parent).unwrap();
    let pinned = File::open(&parent).unwrap();
    // SAFETY: only this qualification's newly created pinned directory changes.
    assert_eq!(unsafe { libc::fchown(pinned.as_raw_fd(), 0, 60001) }, 0);
    pinned
        .set_permissions(std::fs::Permissions::from_mode(0o2710))
        .unwrap();
    let config = config(&parent, /*gid*/ 60001);
    let paths: Vec<_> = validate_runtime_lanes(&config)
        .unwrap()
        .into_iter()
        .map(|(_, path)| path.clone())
        .collect();
    let mut called = 0;
    let mut clients = Vec::new();
    let bound = bind_runtime_lanes(&config, || {
        called += 1;
        for path in &paths {
            // Exactly one actual connect per original lane. A pathname alone
            // cannot satisfy this check before the socket is listening.
            clients.push(UnixStream::connect(path)?);
            let node = std::fs::symlink_metadata(path)?;
            assert_eq!(
                (node.uid(), node.gid(), node.mode() & 0o7777),
                (0, 60001, 0o660)
            );
        }
        Ok(())
    })
    .unwrap();
    assert_eq!((called, clients.len(), bound.listeners.len()), (1, 5, 5));
    for (_, listener) in &bound.listeners {
        let (accepted, _) = listener.accept().unwrap();
        assert!(accepted.peer_addr().unwrap().is_unnamed());
    }
    drop((clients, bound));
    assert!(paths.iter().all(|path| !path.exists()));

    let mut failed_calls = 0;
    let error = bind_runtime_lanes(&config, || {
        failed_calls += 1;
        Err(io::Error::other("one-shot handoff refused"))
    })
    .err()
    .unwrap();
    assert_eq!(
        (failed_calls, error.to_string()),
        (1, "one-shot handoff refused".into())
    );
    assert!(paths.iter().all(|path| !path.exists()));

    // A partial bind failure never announces readiness or removes the
    // pre-existing socket it did not create.
    let occupied = UnixListener::bind(&config.sockets.checkpoint).unwrap();
    let mut premature = false;
    assert!(
        bind_runtime_lanes(&config, || {
            premature = true;
            Ok(())
        })
        .is_err()
    );
    assert!(!premature);
    assert_eq!(
        paths.iter().map(|path| path.exists()).collect::<Vec<_>>(),
        vec![false, false, true, false, false]
    );
    drop(occupied);
}
