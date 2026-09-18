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


struct DispatchAuthorizingLease {
    authorized: Option<oneshot::Sender<()>>,
    terminal: oneshot::Sender<ModelProviderTerminal>,
    fail_authorization: bool,
}

impl ModelProviderAttemptLease for DispatchAuthorizingLease {
    fn authorize_dispatch(&mut self) -> ModelProviderPolicyFuture<'_, ()> {
        if let Some(authorized) = self.authorized.take() {
            let _ = authorized.send(());
        }
        let result = if self.fail_authorization {
            Err(codex_extension_api::ModelProviderPolicyError::new(
                "test_dispatch_denied",
                "test dispatch denied",
            ))
        } else {
            Ok(())
        };
        Box::pin(std::future::ready(result))
    }

    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        let _ = self.terminal.send(terminal);
        Box::pin(std::future::ready(Ok(())))
    }
}

#[tokio::test]
async fn dispatch_authorization_is_single_use_and_precedes_terminal() {
    let (authorized, authorized_rx) = oneshot::channel();
    let (terminal, terminal_rx) = oneshot::channel();
    let owner = ProviderAttemptOwner::new_with_dispatch_probe(
        Box::new(DispatchAuthorizingLease {
            authorized: Some(authorized),
            terminal,
            fail_authorization: false,
        }),
        Box::new(|| false),
    );

    owner
        .authorize_dispatch()
        .await
        .expect("first dispatch authorization should succeed");
    authorized_rx
        .await
        .expect("lease should observe dispatch authorization");
    let error = owner
        .authorize_dispatch()
        .await
        .expect_err("dispatch authorization must be single-use");
    assert_eq!(
        error.reason_code(),
        "model_provider_policy_dispatch_already_authorized"
    );

    owner
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "test_complete".to_string(),
        })
        .await
        .expect("terminal should still close the lease");
    assert!(matches!(
        terminal_rx.await.expect("terminal should be observed"),
        ModelProviderTerminal::NotDispatched { .. }
    ));
}

#[tokio::test]
async fn failed_dispatch_authorization_still_closes_as_not_dispatched_on_drop() {
    let (authorized, authorized_rx) = oneshot::channel();
    let (terminal, terminal_rx) = oneshot::channel();
    let owner = ProviderAttemptOwner::new_with_dispatch_probe(
        Box::new(DispatchAuthorizingLease {
            authorized: Some(authorized),
            terminal,
            fail_authorization: true,
        }),
        Box::new(|| false),
    );

    let error = owner
        .authorize_dispatch()
        .await
        .expect_err("failed final authorization must block dispatch");
    assert_eq!(error.reason_code(), "test_dispatch_denied");
    authorized_rx
        .await
        .expect("lease should observe attempted dispatch authorization");
    drop(owner);

    assert_eq!(
        terminal_rx.await.expect("dropped owner should finish lease"),
        ModelProviderTerminal::NotDispatched {
            reason_code: "model_provider_policy_owner_dropped_before_dispatch".to_string(),
        }
    );
}
