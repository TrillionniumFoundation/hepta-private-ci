//! Deterministic original-authority barriers over two real store connections.
//! The clock and issuer are explicit qualification fixtures, not host trust.

use codex_hepta_automation::*;
use codex_hepta_contracts::*;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use tokio::sync::Notify;

struct AdmissionClock {
    calls: AtomicUsize,
    block_at: AtomicUsize,
    entered: Notify,
    release: Mutex<mpsc::Receiver<()>>,
}

impl AuthorityClock for AdmissionClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if call == self.block_at.load(Ordering::SeqCst) {
            self.entered.notify_one();
            self.release
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .recv_timeout(Duration::from_secs(5))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        SystemAuthorityClock.now_unix_ms()
    }
}

pub(super) struct GatedAuthority {
    pub(super) authority: FinalUseAuthority,
    pub(super) signed: SignedFinalUseGrant,
    _directory: tempfile::TempDir,
    clock: Arc<AdmissionClock>,
    release: Option<mpsc::Sender<()>>,
}

impl GatedAuthority {
    pub(super) fn new(binding: FinalUseBinding, grant_id: &str, block_at: usize) -> Self {
        let (original, signed, directory) = super::super::final_use(binding, grant_id);
        drop(original);
        let (release, receiver) = mpsc::channel();
        let clock = Arc::new(AdmissionClock {
            calls: AtomicUsize::new(0),
            block_at: AtomicUsize::new(0),
            entered: Notify::new(),
            release: Mutex::new(receiver),
        });
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "security-owner".into(),
            SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
            clock.clone(),
        )
        .expect("reopen original test authority with controlled clock");
        clock.calls.store(0, Ordering::SeqCst);
        clock.block_at.store(block_at, Ordering::SeqCst);
        Self {
            authority,
            signed,
            _directory: directory,
            clock,
            release: Some(release),
        }
    }

    pub(super) async fn entered(&self) {
        tokio::time::timeout(Duration::from_secs(3), self.clock.entered.notified())
            .await
            .expect("original authority reached the selected admission boundary");
    }

    pub(super) fn release(&mut self) {
        self.release
            .take()
            .expect("release barrier once")
            .send(())
            .expect("release original authority");
    }
}

pub(super) struct FileEffectDriver {
    pub(super) calls: Arc<AtomicUsize>,
    path: PathBuf,
}

impl FileEffectDriver {
    pub(super) fn new(path: PathBuf) -> Self {
        Self {
            calls: Arc::new(AtomicUsize::new(0)),
            path,
        }
    }

    fn enter(&mut self, bytes: &[u8]) -> AuthorizedEffectProviderReceipt {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let mut file = File::create_new(&self.path).expect("one controlled provider entry");
        file.write_all(bytes).expect("exact effect payload");
        file.sync_all().expect("retained fixture effect");
        File::open(self.path.parent().expect("owned fixture parent"))
            .expect("fixture directory")
            .sync_all()
            .expect("durable fixture publication");
        // A deliberate lost acknowledgement keeps the original attempt
        // indeterminate until this explicit provider fixture reconciles it.
        AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: Sha256Digest::for_bytes(b"fixture contact without terminal ACK"),
        }
    }
}

impl AuthorizedEffectDriver for FileEffectDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        Ok(self.enter(request.wire_payload))
    }
}

impl AsyncAuthorizedEffectDriver for FileEffectDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move { Ok(self.enter(request.wire_payload)) })
    }
}

pub(super) struct OwnedDispatch {
    pub(super) store: AutomationStore,
    pub(super) authority: FinalUseAuthority,
    pub(super) signed: SignedFinalUseGrant,
    pub(super) effect: AuthorizedEffectIntent,
    pub(super) fence: TaskFlowFence,
    pub(super) binding: FinalUseBinding,
    pub(super) driver: FileEffectDriver,
}

impl OwnedDispatch {
    pub(super) fn spawn(
        mut self,
        asynchronous: bool,
        now_ms: u64,
    ) -> tokio::task::JoinHandle<Result<TaskFlowStepReceipt, AuthorizedEffectError>> {
        tokio::spawn(async move {
            if asynchronous {
                self.store
                    .execute_authorized_taskflow_effect_async(
                        &self.authority,
                        &mut self.driver,
                        &self.effect,
                        super::super::EFFECT_PAYLOAD,
                        &self.fence,
                        &self.signed,
                        &self.binding,
                        "race-effect-dispatch",
                        now_ms,
                    )
                    .await
            } else {
                self.store
                    .execute_authorized_taskflow_effect(
                        &self.authority,
                        &mut self.driver,
                        &self.effect,
                        super::super::EFFECT_PAYLOAD,
                        &self.fence,
                        &self.signed,
                        &self.binding,
                        "race-effect-dispatch",
                        now_ms,
                    )
                    .await
            }
        })
    }
}
