//! Actual file effect and original-store setup for same-clock regressions.
#![allow(
    clippy::expect_used,
    reason = "controlled file effect and original owner fixture"
)]

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowClockClaim;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;
use tokio::sync::oneshot;

use super::super::EFFECT_PAYLOAD;
use super::super::Fixture;
use super::super::binding;
use super::super::definition;
use super::super::fence;
use super::fixture::Clock;
use super::fixture::Security;

pub(super) async fn queued_store(fixture: &Fixture, run_id: &str) -> AutomationStore {
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("original store");
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &fence(), /*now_ms*/ 1_000)
        .await
        .expect("definition");
    store
        .create_taskflow_run(
            run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "clock-fixture-thread",
            /*now_ms*/ 1_000,
        )
        .await
        .expect("unleased run");
    store
}

pub(super) async fn activate(
    store: &AutomationStore,
    claim: &TaskFlowClockClaim<'_>,
    effect: &AuthorizedEffectIntent,
) {
    let now = claim.run().updated_at_ms;
    let start = TaskFlowCommand::new(
        &effect.run_id,
        "clock-start",
        claim.fence().clone(),
        claim.run().revision,
        TaskFlowTransition::Start,
        now,
    )
    .expect("start");
    store
        .apply_taskflow_command(&start)
        .await
        .expect("original start");
    let digest = effect.digest().expect("effect digest");
    store
        .prepare_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            claim.fence(),
            &digest,
            &effect.payload_digest,
            "clock-prepare",
            now,
        )
        .await
        .expect("original prepare");
    store
        .claim_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            claim.fence(),
            &digest,
            &effect.payload_digest,
            "clock-step-claim",
            now,
        )
        .await
        .expect("original step claim");
}

pub(super) struct FileDriver {
    pub(super) calls: Arc<AtomicUsize>,
    pub(super) pause: Option<(Arc<Notify>, Arc<Notify>)>,
    pub(super) invalidate_clock: Option<Arc<Clock>>,
    pub(super) reject_before_contact: bool,
    path: PathBuf,
}

impl FileDriver {
    pub(super) fn new(path: PathBuf) -> Self {
        Self {
            path,
            calls: Arc::new(AtomicUsize::new(/*v*/ 0)),
            pause: None,
            invalidate_clock: None,
            reject_before_contact: false,
        }
    }

    fn record(&mut self, bytes: &[u8]) -> AuthorizedEffectProviderReceipt {
        self.calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
        let mut file = File::create_new(&self.path).expect("one actual file effect");
        file.write_all(bytes).expect("exact effect bytes");
        file.sync_all().expect("durable fixture file");
        File::open(self.path.parent().expect("owned fixture directory"))
            .expect("fixture directory")
            .sync_all()
            .expect("publication witness");
        if let Some(clock) = &self.invalidate_clock {
            clock.unavailable(/*value*/ true);
        }
        AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: Sha256Digest::for_bytes(
                b"actual file entry with deliberately uncertain terminal ACK",
            ),
        }
    }
}

impl AuthorizedEffectDriver for FileDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        if self.reject_before_contact {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        Ok(self.record(request.wire_payload))
    }
}

impl AsyncAuthorizedEffectDriver for FileDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if self.reject_before_contact {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            let receipt = self.record(request.wire_payload);
            if let Some((entered, release)) = &self.pause {
                entered.notify_one();
                release.notified().await;
            }
            Ok(receipt)
        })
    }
}

pub(super) struct RunningDispatch {
    pub(super) ready: oneshot::Receiver<()>,
    pub(super) start: oneshot::Sender<()>,
    pub(super) task: tokio::task::JoinHandle<Result<TaskFlowStepReceipt, AuthorizedEffectError>>,
}

pub(super) fn spawn_dispatch(
    store: AutomationStore,
    security: Security,
    effect: AuthorizedEffectIntent,
    mut driver: FileDriver,
    lease_duration: u64,
    asynchronous: bool,
) -> RunningDispatch {
    let (ready_sender, ready) = oneshot::channel();
    let (start, start_receiver) = oneshot::channel();
    let task = tokio::spawn(async move {
        // Capture the entire fixture. Disjoint field capture would otherwise
        // drop its uncaptured TempDir when spawn_dispatch returns, removing the
        // original authority journal before its nonce can be durably claimed.
        #[allow(
            clippy::redundant_locals,
            reason = "move the owned authority directory into the task with its handles"
        )]
        let security = security;
        let expected = binding(&effect);
        let claim = store
            .claim_taskflow_run_with_authority_clock(
                &security.authority,
                &effect.run_id,
                &fence(),
                lease_duration,
            )
            .await?;
        activate(&store, &claim, &effect).await;
        security.clock.reset_calls();
        ready_sender
            .send(())
            .expect("controller observes ready claim");
        start_receiver.await.expect("explicit controlled start");
        let result = if asynchronous {
            claim
                .execute_authorized_effect_async(
                    &mut driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &security.signed,
                    &expected,
                    "clock-effect",
                )
                .await
        } else {
            claim
                .execute_authorized_effect(
                    &mut driver,
                    &effect,
                    EFFECT_PAYLOAD,
                    &security.signed,
                    &expected,
                    "clock-effect",
                )
                .await
        };
        if let Err(error) = &result {
            // Only synthetic test errors are printed; expose an early owner
            // rejection instead of leaving a later barrier timeout unexplained.
            eprintln!("clock fixture dispatch returned: {error:?}");
        }
        result
    });
    RunningDispatch { ready, start, task }
}
