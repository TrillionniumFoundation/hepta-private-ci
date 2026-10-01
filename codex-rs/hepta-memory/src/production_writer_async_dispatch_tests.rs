use super::final_use_dispatch_tests::FinalUseVerifier;
use super::final_use_dispatch_tests::bound_operation;
use super::final_use_dispatch_tests::production_authority;
use super::final_use_dispatch_tests::signed_final_use;
use super::final_use_dispatch_tests::store;
use super::final_use_dispatch_tests::test_nonce;
use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::task::JoinHandle;

/// Signals from inside the lazy future, then suspends the actual target effect.
struct SuspendedTarget {
    entered: Notify,
    release: Notify,
    calls: AtomicUsize,
    outcome: ProductionTargetOutcome,
}

impl ProductionOutboxTarget for SuspendedTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
            self.entered.notify_one();
            self.release.notified().await;
            self.outcome.clone()
        })
    }
}

impl FinalUseProductionOutboxTarget for SuspendedTarget {
    fn destination_id(&self) -> &str {
        "destination:async-effect"
    }
}

struct Fixture {
    _temp: TempDir,
    writer: ProductionDurableWriter,
    final_use: FinalUseAuthority,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    target: Arc<SuspendedTarget>,
    signed: SignedFinalUseGrant,
    binding: FinalUseBinding,
    queued: ProductionQueuedReceipt,
}

impl Fixture {
    async fn new(outcome: ProductionTargetOutcome) -> Self {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let writer = ProductionDurableWriter::open(
            store,
            production_authority(owner.clone()),
            &FinalUseVerifier,
            "production:h4:async-effect",
            /*generation*/ 1,
        )
        .await
        .expect("writer");
        let directory = temp.path().join("final-use-async");
        std::fs::create_dir(&directory).expect("authority directory");
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(/*mode*/ 0o700))
            .expect("authority permissions");
        let issuer = SigningKey::from_bytes(&[85; 32]);
        let final_use = FinalUseAuthority::open_state_dir(
            &directory,
            "final-use-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final-use authority");
        let target = Arc::new(SuspendedTarget {
            entered: Notify::new(),
            release: Notify::new(),
            calls: AtomicUsize::new(/*v*/ 0),
            outcome,
        });
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(final_use.clone(), target.clone());
        let payload = "{\"fact\":\"async-effect\"}";
        let queued = writer
            .prepare_operation(
                bound_operation(
                    &owner,
                    "occurrence:async-effect",
                    target.destination_id(),
                    payload,
                ),
                "memory.write",
                payload,
            )
            .await
            .expect("queued");
        let binding = writer
            .final_use_binding(&queued, target.destination_id())
            .await
            .expect("final-use binding");
        let signed = signed_final_use(
            &issuer,
            binding.clone(),
            "final-use-async-effect",
            test_nonce("final-use-async-effect"),
        );
        Self {
            _temp: temp,
            writer,
            final_use,
            dispatcher,
            target,
            signed,
            binding,
            queued,
        }
    }

    async fn dispatch_started(
        &self,
    ) -> JoinHandle<Result<ProductionDispatchReceipt, ProductionWriterError>> {
        let dispatcher = self.dispatcher.clone();
        let writer = self.writer.clone();
        let signed = self.signed.clone();
        let binding = self.binding.clone();
        let queued = self.queued.clone();
        let dispatch = tokio::spawn(async move {
            dispatcher
                .dispatch(&writer, &signed, &binding, queued)
                .await
        });
        tokio::time::timeout(
            Duration::from_secs(/*secs*/ 30),
            self.target.entered.notified(),
        )
        .await
        .expect("dispatch reached the suspended target future");
        dispatch
    }

    fn revoke(&self) -> Result<(), FinalUseError> {
        self.final_use.update_revocations(FinalUseRevocations {
            authority_epoch: 71,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([self.signed.grant.grant_id.clone()]),
        })
    }
}

#[tokio::test]
async fn async_dispatch_holds_final_use_fence_until_target_completion() {
    let fixture = Fixture::new(ProductionTargetOutcome::Committed {
        receipt: "target:async-committed".to_string(),
    })
    .await;
    let dispatch = fixture.dispatch_started().await;
    assert_eq!(fixture.revoke(), Err(FinalUseError::DispatchInProgress));
    assert_eq!(
        fixture
            .writer
            .status(&fixture.queued.occurrence_key)
            .await
            .expect("entered status"),
        LocalOutcomeState::Indeterminate
    );
    fixture.target.release.notify_one();
    let receipt = dispatch
        .await
        .expect("dispatch task")
        .expect("dispatch result");
    assert_eq!(
        (
            receipt.state,
            receipt.target_disposition,
            receipt.target_receipt
        ),
        (
            LocalOutcomeState::Committed,
            ProductionTargetDisposition::Committed,
            Some("target:async-committed".to_string())
        )
    );
    assert_eq!(fixture.revoke(), Ok(()));
    assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn async_dispatch_failure_releases_fence_without_committed_receipt() {
    for (outcome, state, disposition) in [
        (
            ProductionTargetOutcome::NotApplied {
                reason: "CAS mismatch".to_string(),
            },
            LocalOutcomeState::Rejected,
            ProductionTargetDisposition::NotApplied,
        ),
        (
            ProductionTargetOutcome::Rejected {
                reason: "invalid input".to_string(),
            },
            LocalOutcomeState::Rejected,
            ProductionTargetDisposition::Rejected,
        ),
        (
            ProductionTargetOutcome::Indeterminate {
                reason: "uncertain commit".to_string(),
            },
            LocalOutcomeState::Indeterminate,
            ProductionTargetDisposition::Indeterminate,
        ),
    ] {
        let fixture = Fixture::new(outcome).await;
        let dispatch = fixture.dispatch_started().await;
        assert_eq!(fixture.revoke(), Err(FinalUseError::DispatchInProgress));
        fixture.target.release.notify_one();
        let receipt = dispatch
            .await
            .expect("dispatch task")
            .expect("dispatch result");
        assert_eq!(
            (
                receipt.state,
                receipt.target_disposition,
                receipt.target_receipt
            ),
            (state, disposition, None)
        );
        assert_eq!(
            fixture
                .writer
                .status(&fixture.queued.occurrence_key)
                .await
                .expect("terminal status"),
            state
        );
        assert_eq!(fixture.revoke(), Ok(()));
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn cancelled_async_dispatch_releases_fence_and_preserves_indeterminate_state() {
    let fixture = Fixture::new(ProductionTargetOutcome::Committed {
        receipt: "target:must-not-commit".to_string(),
    })
    .await;
    let dispatch = fixture.dispatch_started().await;
    assert_eq!(fixture.revoke(), Err(FinalUseError::DispatchInProgress));
    dispatch.abort();
    assert!(
        dispatch
            .await
            .expect_err("dispatch was cancelled")
            .is_cancelled()
    );
    assert_eq!(fixture.revoke(), Ok(()));
    assert_eq!(
        fixture
            .writer
            .status(&fixture.queued.occurrence_key)
            .await
            .expect("cancelled status"),
        LocalOutcomeState::Indeterminate
    );
    assert!(matches!(
        fixture
            .dispatcher
            .dispatch(
                &fixture.writer,
                &fixture.signed,
                &fixture.binding,
                fixture.queued.clone()
            )
            .await,
        Err(ProductionWriterError::StaleReceipt)
    ));
    assert_eq!(
        fixture.target.calls.load(Ordering::SeqCst),
        1,
        "cancelled effect cannot be blindly resent"
    );
}
