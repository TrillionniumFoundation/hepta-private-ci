use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use tokio::sync::oneshot;

use super::ProviderAttemptOwner;

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

fn owner(
    transport_invoked: bool,
) -> (
    ProviderAttemptOwner,
    oneshot::Receiver<ModelProviderTerminal>,
    Arc<AtomicBool>,
) {
    let (terminal, observed) = oneshot::channel();
    let dispatch_probe = Arc::new(AtomicBool::new(transport_invoked));
    let dispatch_probe_for_owner = Arc::clone(&dispatch_probe);
    (
        ProviderAttemptOwner::new_with_dispatch_probe(
            Box::new(RecordingLease { terminal }),
            Box::new(move || dispatch_probe_for_owner.load(Ordering::Acquire)),
        ),
        observed,
        dispatch_probe,
    )
}

#[tokio::test]
async fn dropped_owner_records_not_dispatched_before_transport() {
    let (owner, observed, _dispatch_probe) = owner(false);

    drop(owner);

    assert_eq!(
        observed.await.expect("owner should finish its lease"),
        ModelProviderTerminal::NotDispatched {
            reason_code: "model_provider_policy_owner_dropped_before_dispatch".to_string(),
        }
    );
}

#[tokio::test]
async fn dropped_owner_records_indeterminate_after_transport() {
    let (owner, observed, dispatch_probe) = owner(false);
    dispatch_probe.store(true, Ordering::Release);

    drop(owner);

    assert_eq!(
        observed.await.expect("owner should finish its lease"),
        ModelProviderTerminal::Indeterminate {
            reason_code: "model_provider_policy_owner_dropped_after_dispatch".to_string(),
            partial_response_sha256: None,
        }
    );
}

#[tokio::test]
async fn explicit_terminal_is_acknowledged_exactly_once() {
    let (owner, observed, _dispatch_probe) = owner(false);
    let terminal = ModelProviderTerminal::Rejected {
        reason_code: "provider_rejected".to_string(),
    };

    owner
        .finish(terminal.clone())
        .await
        .expect("explicit terminal should be acknowledged");

    assert_eq!(
        observed.await.expect("owner should finish its lease"),
        terminal
    );
}
