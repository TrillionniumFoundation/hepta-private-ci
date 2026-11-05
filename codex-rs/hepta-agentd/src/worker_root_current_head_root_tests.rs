//! A current-head constraint on the actual Worker Load lane. This does not
//! activate final-use grants, ordinary entry, or provider/tool effects.

use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostIssuerTransportError;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original issuer and frozen Worker required"]
fn root_worker_original_issuer_revoke_fences_an_older_consumer_floor() {
    let fixture = LaneFixture::open();
    let session = fixture.original.session.as_ref().unwrap();
    session.provision_worker_frontier_fresh().unwrap();
    let floor = fixture.worker_path().join("consumer-floor");
    let slot = fixture.worker_path().join("current-slot");
    let other_consumers = original_consumer_records(&fixture);
    let (mut worker, root) = child(&fixture.original, "lanes-root-head-revoked");
    let mut output = worker.child.stdout.take().unwrap();
    let mut input = worker.child.stdin.take().unwrap();
    let held = session.register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    let (ready, result, head, server_result, floor_before, slot_before) = std::thread::scope(|scope| {
        let server = scope.spawn(|| held.serve_worker_lanes(Duration::from_secs(5), Duration::from_secs(15)));
        let ready = read_message(&mut output);
        assert_eq!(ready["kind"], "worker_floor_ready_before_original_revoke");
        let prior: FinalUseRevocations = serde_json::from_value(ready["observation"]["revocations"].clone()).unwrap();
        let initial: FinalUseFrontier = serde_json::from_value(ready["frontier"].clone()).unwrap();
        assert_eq!((initial.authority_epoch, initial.revocation_revision), (prior.authority_epoch, prior.revision));
        assert_eq!(frontier_json(&floor), ready["frontier"]);
        assert_eq!(frontier_json(&slot)["state"]["phase"], "Serving");
        let floor_before = private_records(&floor);
        let slot_before = private_records(&slot);
        let grant_id = "worker-current-head-original-root-revocation";
        // Existing cfg(test) forwarding reaches the SAME retained Root issuer.
        // It neither constructs authority nor selects a clock, key or signer.
        let head = session.service.revoke_worker_journal_qualification_grant(grant_id).unwrap();
        let mut expected = prior;
        expected.revision = expected.revision.checked_add(1).unwrap();
        expected.revoked_grant_ids.insert(grant_id.into());
        assert_eq!(head, expected);
        assert_eq!(private_records(&floor), floor_before);
        input.write_all(&[2]).unwrap();
        let result = read_message(&mut output);
        let server_result = server.join().unwrap();
        (ready, result, head, server_result, floor_before, slot_before)
    });
    worker.child.stdout = Some(output);
    worker.child.stdin = Some(input);
    worker.finish();

    assert_eq!(result["kind"], "worker_floor_current_head_result");
    assert_eq!(result["current_observation"]["revocations"], serde_json::to_value(&head).unwrap());
    assert_eq!(result["current_writer_proof"], ready["writer_proof"]);
    // Prove live original Root clock/issuer/writer after the denied operation;
    // an expired lease or failed Root setup cannot satisfy this regression.
    let (live_head, live_proof, live_deadline) = session.service.with_worker_floor_fence(
        /*expected*/ None,
        |view| Ok((view.head.clone(), view.writer_proof.clone(), view.observed_unix_ms < view.expires_at_unix_ms)),
    ).unwrap();
    assert_eq!(live_head, head);
    assert_eq!(serde_json::to_value(live_proof).unwrap(), ready["writer_proof"]);
    assert!(live_deadline);
    assert_eq!(
        (result["initial_load_refused"].as_bool(), result["retry_load_refused"].as_bool(), result["later_observation_refused"].as_bool()),
        (Some(true), Some(true), Some(true)),
        "the actual Worker Load must reject an older floor after the original issuer revoke and permanently fence the same receipt",
    );
    let error = server_result.expect_err("Root must refuse the stale Worker consumer response");
    assert!(matches!(
        error.get_ref().and_then(|error| error.downcast_ref::<HostIssuerTransportError>()),
        Some(HostIssuerTransportError::Unavailable),
    ));
    assert_eq!(private_records(&floor), floor_before);
    assert_eq!(private_records(&slot), slot_before);
    assert_eq!(original_consumer_records(&fixture), other_consumers);
    assert_eq!(result["effect_authorization_available"], false);
}

fn read_message(output: &mut std::process::ChildStdout) -> serde_json::Value {
    let mut descriptor = libc::pollfd { fd: output.as_raw_fd(), events: libc::POLLIN, revents: 0 };
    // SAFETY: the retained original Child owns this stdout.
    // Poll up to ten seconds for first readability. Following read_exact calls
    // retain the original runner bound, not a ten-second whole-frame deadline.
    assert!(unsafe { libc::poll(&mut descriptor, 1, 10_000) } > 0);
    let mut length = [0; 4];
    output.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=64 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    output.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
