// Diagnostic for the unchanged #210 / #218 broker. Not executed in this audit.
// Run only in an isolated exact-source checkout as ui/broker/tests/session_admission_repro.rs.
use trill_ui_broker::{
    Broker, Capability, ClientHello, DenialCode, OfflineDraft, PeerCredentials, Request, Response,
    SameUidAuthenticator,
};

fn draft() -> Request {
    Request::Draft {
        draft: OfflineDraft {
            draft_id: "session-capacity-diagnostic".into(),
            scope_id: "scope-a".into(),
            text_digest: "a".repeat(64),
            created_unix_ms: 1,
        },
    }
}

#[test]
fn repeated_valid_same_peer_admissions_remain_live_until_explicit_close() {
    let mut broker = Broker::new();
    let auth = SameUidAuthenticator { expected_uid: 1000 };
    let mut handles = Vec::new();
    for _ in 0..4096 {
        let (handle, _) = broker
            .open_session(
                &auth,
                ClientHello {
                    protocol_version: 1,
                    client_id: "desktop-shell".into(),
                    session_nonce: "0123456789abcdef".into(),
                    requested_capabilities: vec![Capability::OfflineDraft],
                },
                PeerCredentials { pid: 42, uid: 1000, gid: 1000 },
            )
            .expect("no admission-count ceiling at the pinned source");
        handles.push(handle);
    }
    for handle in &handles {
        assert!(matches!(broker.handle(handle, draft()), Response::DraftAccepted { .. }));
    }
    broker.close_session(&handles[0]);
    assert!(matches!(
        broker.handle(&handles[0], draft()),
        Response::Denied { code: DenialCode::UnauthenticatedSession, .. }
    ));
    assert!(matches!(broker.handle(&handles[1], draft()), Response::DraftAccepted { .. }));
}
