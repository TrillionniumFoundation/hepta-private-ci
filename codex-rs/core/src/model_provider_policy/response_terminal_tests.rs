use codex_api::RequestDispatchMetadata;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use tokio::sync::oneshot;

use super::ProviderResponseTerminal;
use crate::model_provider_policy::attempt_owner::ProviderAttemptOwner;
use crate::model_provider_policy::binding::bytes_sha256;
use crate::model_provider_policy::binding::canonical_sha256;

struct RecordingLease {
    terminal: oneshot::Sender<ModelProviderTerminal>,
}

impl ModelProviderAttemptLease for RecordingLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        let _ = self.terminal.send(terminal);
        Box::pin(std::future::ready(Ok(())))
    }
}

fn pending() -> (
    ProviderResponseTerminal,
    oneshot::Receiver<ModelProviderTerminal>,
) {
    let (terminal, observed) = oneshot::channel();
    let owner = ProviderAttemptOwner::new(
        Box::new(RecordingLease { terminal }),
        RequestDispatchMetadata::new(),
    );
    (ProviderResponseTerminal::new(Some(owner)), observed)
}

fn item() -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "assistant".to_string(),
        content: vec![ContentItem::OutputText {
            text: "bounded output".to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

#[tokio::test]
async fn completed_stream_binds_exact_observation() {
    let (mut terminal, observed) = pending();
    let items = vec![item()];
    let usage = Some(serde_json::json!({"input": 1, "output": 2}));

    assert!(
        terminal
            .finish_completed("response-1", &items, &usage, Some(true))
            .await
            .expect("completed terminal should persist")
    );

    assert_eq!(
        observed.await.expect("lease should observe terminal"),
        ModelProviderTerminal::Completed {
            response_id_sha256: bytes_sha256(b"response-1").expect("response digest"),
            response_items_sha256: canonical_sha256(&items).expect("items digest"),
            token_usage_sha256: canonical_sha256(&usage).expect("usage digest"),
            end_turn: Some(true),
        }
    );
}

#[tokio::test]
async fn unary_completion_does_not_invent_stream_fields() {
    let (mut terminal, observed) = pending();
    let items = vec![item()];

    assert!(
        terminal
            .finish_completed_unary(&items)
            .await
            .expect("unary terminal should persist")
    );

    assert_eq!(
        observed.await.expect("lease should observe terminal"),
        ModelProviderTerminal::CompletedUnary {
            response_items_sha256: canonical_sha256(&items).expect("items digest"),
        }
    );
}

#[tokio::test]
async fn partial_output_is_bound_into_indeterminate_terminal() {
    let (mut terminal, observed) = pending();
    let items = vec![item()];

    assert!(
        terminal
            .finish_indeterminate("provider_stream_failed", &items)
            .await
            .expect("indeterminate terminal should persist")
    );

    assert_eq!(
        observed.await.expect("lease should observe terminal"),
        ModelProviderTerminal::Indeterminate {
            reason_code: "provider_stream_failed".to_string(),
            partial_response_sha256: Some(canonical_sha256(&items).expect("items digest")),
        }
    );
}

#[tokio::test]
async fn inactive_state_preserves_fast_path_and_second_terminal_fails() {
    let mut inactive = ProviderResponseTerminal::new(None);
    assert!(
        !inactive
            .finish_indeterminate("ignored", &[item()])
            .await
            .expect("inactive terminal should be a no-op")
    );

    let (mut terminal, _observed) = pending();
    terminal
        .finish_rejected("provider_rejected")
        .await
        .expect("first terminal should persist");
    let error = terminal
        .finish_not_dispatched("second_terminal")
        .await
        .expect_err("second terminal must fail closed");
    assert_eq!(
        error.reason_code(),
        "model_provider_policy_terminal_already_committed"
    );
}
