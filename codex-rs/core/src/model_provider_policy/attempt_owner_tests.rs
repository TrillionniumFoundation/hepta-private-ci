use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use tokio::sync::oneshot;

use super::ProviderAttemptOwner;
use codex_extension_api::ModelProviderSha256Digest;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;
use tokio::sync::Semaphore;

struct BindingLease {
    terminal: oneshot::Sender<ModelProviderTerminal>,
    entered: Arc<Notify>,
    release: Arc<Semaphore>,
}

impl ModelProviderAttemptLease for BindingLease {
    fn encoded_body_required(&self) -> bool {
        true
    }
    fn bind_encoded_body_v1<'a>(
        &'a mut self,
        _digest: ModelProviderSha256Digest,
        _bytes: u64,
    ) -> ModelProviderPolicyFuture<'a, ()> {
        self.entered.notify_one();
        Box::pin(async move {
            self.release
                .acquire()
                .await
                .expect("test binding gate")
                .forget();
            Ok(())
        })
    }
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        let _ = self.terminal.send(terminal);
        Box::pin(async { Ok(()) })
    }
}

struct BindingCase {
    owner: ProviderAttemptOwner,
    terminal: oneshot::Receiver<ModelProviderTerminal>,
    entered: Arc<Notify>,
    release: Arc<Semaphore>,
    dispatched: Arc<AtomicBool>,
}

impl BindingCase {
    fn new() -> Self {
        let (sender, terminal) = oneshot::channel();
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Semaphore::new(0));
        let dispatched = Arc::new(AtomicBool::new(false));
        let probe = dispatched.clone();
        let owner = ProviderAttemptOwner::new_with_dispatch_probe(
            Box::new(BindingLease {
                terminal: sender,
                entered: entered.clone(),
                release: release.clone(),
            }),
            Box::new(move || probe.load(Ordering::Acquire)),
        );
        Self {
            owner,
            terminal,
            entered,
            release,
            dispatched,
        }
    }
}

#[tokio::test]
async fn retained_weak_body_observer_cannot_keep_cancelled_owner_alive() {
    let case = BindingCase::new();
    let observer = case
        .owner
        .encoded_observer(/*prior*/ None)
        .expect("required observer");
    drop(case.owner);
    let terminal = tokio::time::timeout(std::time::Duration::from_secs(3), case.terminal)
        .await
        .expect("weak observer must not retain owner")
        .expect("original terminal");
    assert!(matches!(
        terminal,
        ModelProviderTerminal::NotDispatched { .. }
    ));
    assert!(observer.observe_encoded_body(b"no owner").await.is_err());
}

#[tokio::test]
async fn cancelled_binding_settles_original_owner_once_with_dispatch_witness() {
    for dispatched in [false, true] {
        let case = BindingCase::new();
        let observer = case
            .owner
            .encoded_observer(/*prior*/ None)
            .expect("required observer");
        let binding =
            tokio::spawn(async move { observer.observe_encoded_body(b"complete body").await });
        tokio::time::timeout(std::time::Duration::from_secs(3), case.entered.notified())
            .await
            .expect("binding must enter original owner");
        binding.abort();
        assert!(binding.await.expect_err("binding cancelled").is_cancelled());
        case.dispatched.store(dispatched, Ordering::Release);
        drop(case.owner);
        case.release.add_permits(1);
        let terminal = tokio::time::timeout(std::time::Duration::from_secs(3), case.terminal)
            .await
            .expect("owner must settle after binding returns")
            .expect("original terminal");
        let expected = if dispatched {
            ModelProviderTerminal::Indeterminate {
                reason_code: "model_provider_policy_owner_dropped_after_dispatch".into(),
                partial_response_sha256: None,
            }
        } else {
            ModelProviderTerminal::NotDispatched {
                reason_code: "model_provider_policy_owner_dropped_before_dispatch".into(),
            }
        };
        assert_eq!(terminal, expected);
    }
}

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
