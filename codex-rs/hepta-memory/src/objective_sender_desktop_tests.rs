//! Actual original SQLite sender/writer fences with explicit fixture authority.
//! No Core ordering, production Root, model, or native application is simulated
//! as qualified by these storage tests.
use super::test_support::*;
use super::*;
use crate::CognitiveStore;
use crate::cognitive_test_support::layout;
use codex_hepta_types::Digest32;
use serde_json::json;

fn desktop_request(tool: &str, call: &str, request_id: u64) -> ObjectiveSenderRequest {
    let base = request();
    let mut envelope: serde_json::Value = serde_json::from_slice(base.exact_original()).unwrap();
    envelope["message_id"] = format!("desktop-fixture-{call}").into();
    envelope["sequence"] = request_id.into();
    envelope["body"]["source_envelope_json"] =
        json!({"fixture_tool":tool,"call":call}).to_string().into();
    let mut origin = base.origin().clone();
    origin.request_id = request_id;
    origin.original_desktop_thread = Some(OriginalDesktopThreadReference {
        profile: "organ.desktop.thread-tool.v1".into(),
        tool: tool.into(),
        app_server_session_id: "original-session".into(),
        thread_id: "original-thread".into(),
        turn_id: "same-original-turn".into(),
        call_id: call.into(),
        callback_sha256: Digest32::of_bytes(format!("fixture:{tool}:{call}").as_bytes())
            .to_string(),
    });
    ObjectiveSenderRequest::from_original(envelope.to_string(), origin).unwrap()
}

#[tokio::test]
async fn desktop_unknown_turn_retains_first_app_identity_and_never_grants_a_second_send() {
    for (first, later) in [
        ("hepta_notes_replace", "hepta_calculator_evaluate"),
        ("hepta_calculator_evaluate", "hepta_notes_replace"),
    ] {
        let fixture = Fixture::new().await;
        let sender = fixture.sender();
        let original = desktop_request(first, "first", 20);
        let conflicting = desktop_request(later, "later", 21);
        assert_eq!(original.identity().run_id, conflicting.identity().run_id);
        let ticket = sender.retain_before_send(original.clone()).await.unwrap();
        sender.mark_send_started(&ticket).await.unwrap();
        let unknown = observation(
            ObjectiveSenderObservationKind::Submission,
            "{\"status\":\"fixture_submit_unknown\"}",
        );
        sender.retain_observation(&ticket, &unknown).await.unwrap();
        let cut = fixture.store.recovery_anchor().await.unwrap();
        assert!(matches!(
            sender.retain_before_send(conflicting.clone()).await,
            Err(ObjectiveSenderError::AlreadyRetained)
        ));
        let original_read = sender
            .retained_request_for_run(&original.identity().run_id)
            .await
            .unwrap()
            .unwrap();
        assert!(original_read == original);
        assert_eq!(
            original_read
                .origin()
                .original_desktop_thread
                .as_ref()
                .unwrap()
                .tool,
            first
        );
        assert_eq!(sender.retained_owner_requests().await.unwrap().len(), 1);
        // A newly obtained capability still uses the same persistent original
        // owner. Recovered tickets never reacquire the one-shot send permission.
        let recovered_sender = fixture.sender();
        let recovered = recovered_sender
            .recover_pending(original.clone())
            .await
            .unwrap();
        assert!(matches!(
            recovered_sender.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
        assert!(recovered_sender.recover_pending(conflicting).await.is_err());
        assert!(
            recovered_sender
                .snapshot(&recovered)
                .await
                .unwrap()
                .observations
                == vec![unknown]
        );
        assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
        // The original full startup audit must accept this new binding and its
        // immutable chain; this is reopen validation, not a process-crash claim.
        assert!(
            CognitiveStore::open(&layout(&fixture.temp, fixture.writer.owner_agent_id()))
                .await
                .is_ok()
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_desktop_apps_share_the_original_sqlite_send_fence() {
    let fixture = Fixture::new().await;
    let requests = [
        desktop_request("hepta_notes_replace", "notes", 30),
        desktop_request("hepta_calculator_evaluate", "calculator", 31),
    ];
    let barrier = Arc::new(tokio::sync::Barrier::new(2));
    let tasks = requests.map(|request| {
        let sender = fixture.sender();
        let barrier = Arc::clone(&barrier);
        tokio::spawn(async move {
            assert!(
                sender
                    .retained_request_for_run(&request.identity().run_id)
                    .await
                    .unwrap()
                    .is_none()
            );
            barrier.wait().await;
            let result = sender.retain_before_send(request.clone()).await;
            (request, result)
        })
    });
    let [first, second] = tasks;
    let (first, second) = tokio::join!(first, second);
    let (first, first_result) = first.unwrap();
    let (second, second_result) = second.unwrap();
    let (winner, ticket) = match (first_result, second_result) {
        (Ok(ticket), Err(ObjectiveSenderError::AlreadyRetained)) => (first, ticket),
        (Err(ObjectiveSenderError::AlreadyRetained), Ok(ticket)) => (second, ticket),
        _ => panic!("both apps must share exactly one persistent send admission"),
    };
    let sender = fixture.sender();
    sender.mark_send_started(&ticket).await.unwrap();
    let stored = sender.retained_owner_requests().await.unwrap();
    assert!(stored == vec![winner.clone()]);
    let recovered = sender.recover_pending(winner).await.unwrap();
    assert!(matches!(
        sender.mark_send_started(&recovered).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
}
