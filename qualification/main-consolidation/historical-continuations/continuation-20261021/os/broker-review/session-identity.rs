use trill_ui_broker::{
    Broker, Capability, ClientHello, DenialCode, OfflineDraft, PeerCredentials, Request, Response,
    SameUidAuthenticator, SessionHandle,
};

fn open(broker: &mut Broker, capabilities: Vec<Capability>) -> SessionHandle {
    broker
        .open_session(
            &SameUidAuthenticator { expected_uid: 1000 },
            ClientHello {
                protocol_version: 1,
                client_id: "desktop-shell".into(),
                session_nonce: "0123456789abcdef".into(),
                requested_capabilities: capabilities,
            },
            PeerCredentials {
                pid: 42,
                uid: 1000,
                gid: 1000,
            },
        )
        .unwrap()
        .0
}

fn draft() -> Request {
    Request::Draft {
        draft: OfflineDraft {
            draft_id: "draft-a".into(),
            scope_id: "scope-a".into(),
            text_digest: "a".repeat(64),
            created_unix_ms: 1,
        },
    }
}

fn assert_unauthenticated(response: Response) {
    assert!(matches!(
        response,
        Response::Denied {
            code: DenialCode::UnauthenticatedSession,
            ..
        }
    ));
}

#[test]
fn foreign_handle_cannot_use_colliding_session_capabilities() {
    let mut original = Broker::new();
    let foreign = open(&mut original, vec![Capability::Observe]);
    let mut other = Broker::new();
    let local = open(&mut other, vec![Capability::OfflineDraft]);
    assert_eq!(foreign.id(), local.id());

    assert_unauthenticated(other.handle(&foreign, draft()));
    assert!(matches!(
        other.handle(&local, draft()),
        Response::DraftAccepted { .. }
    ));
}

#[test]
fn foreign_handle_cannot_close_colliding_session() {
    let mut original = Broker::new();
    let foreign = open(&mut original, vec![Capability::Observe]);
    let mut other = Broker::new();
    let local = open(&mut other, vec![Capability::OfflineDraft]);
    assert_eq!(foreign.id(), local.id());

    other.close_session(&foreign);
    assert!(matches!(
        other.handle(&local, draft()),
        Response::DraftAccepted { .. }
    ));
}

#[test]
fn stale_handle_cannot_use_restarted_broker() {
    let stale = {
        let mut previous = Broker::new();
        open(&mut previous, vec![Capability::OfflineDraft])
    };
    let mut restarted = Broker::new();
    let local = open(&mut restarted, vec![Capability::OfflineDraft]);
    assert_eq!(stale.id(), local.id());

    assert_unauthenticated(restarted.handle(&stale, draft()));
    restarted.close_session(&stale);
    assert!(matches!(
        restarted.handle(&local, draft()),
        Response::DraftAccepted { .. }
    ));
}

#[test]
fn cloned_handle_shares_only_the_original_session_lifetime() {
    let mut broker = Broker::new();
    let original = open(&mut broker, vec![Capability::OfflineDraft]);
    let cloned = original.clone();
    assert_eq!(original, cloned);
    assert!(matches!(
        broker.handle(&cloned, draft()),
        Response::DraftAccepted { .. }
    ));

    broker.close_session(&cloned);
    assert_unauthenticated(broker.handle(&original, draft()));
    assert_unauthenticated(broker.handle(&cloned, draft()));
    let next = open(&mut broker, vec![Capability::OfflineDraft]);
    assert_ne!(original.id(), next.id());
    assert_unauthenticated(broker.handle(&original, draft()));
    assert!(matches!(
        broker.handle(&next, draft()),
        Response::DraftAccepted { .. }
    ));
}

#[test]
fn equal_local_ids_do_not_make_foreign_handles_equal() {
    let mut original = Broker::new();
    let a = open(&mut original, vec![Capability::Observe]);
    let mut other = Broker::new();
    let b = open(&mut other, vec![Capability::Observe]);
    assert_eq!(a.id(), b.id());
    assert_ne!(a, b);
}
