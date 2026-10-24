//! Explicit existing-clock and signed-grant fixtures; no production trust.
#![allow(
    clippy::expect_used,
    reason = "controlled original-owner fixture invariants"
)]

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use tokio::sync::Notify;

use super::super::NEXT_TEST_NONCE;
use super::super::digest_bytes;

pub(super) struct Clock {
    now: AtomicU64,
    unavailable: AtomicBool,
    calls: AtomicUsize,
    block_at: AtomicUsize,
    changed: Notify,
    entered: Notify,
    release: Mutex<mpsc::Receiver<()>>,
    sender: mpsc::Sender<()>,
}

impl Clock {
    pub(super) fn new(now: u64) -> Arc<Self> {
        let (sender, receiver) = mpsc::channel();
        Arc::new(Self {
            now: AtomicU64::new(now),
            unavailable: AtomicBool::new(/*v*/ false),
            calls: AtomicUsize::new(/*v*/ 0),
            block_at: AtomicUsize::new(/*v*/ 0),
            changed: Notify::new(),
            entered: Notify::new(),
            release: Mutex::new(receiver),
            sender,
        })
    }

    pub(super) fn set(&self, now: u64) {
        self.now.store(now, Ordering::SeqCst);
    }
    pub(super) fn unavailable(&self, value: bool) {
        self.unavailable.store(value, Ordering::SeqCst);
    }
    pub(super) fn reset_calls(&self) {
        self.calls.store(/*val*/ 0, Ordering::SeqCst);
    }
    pub(super) fn block_on(&self, call: usize) {
        self.block_at.store(call, Ordering::SeqCst);
    }
    pub(super) fn release(&self) {
        self.sender.send(()).expect("release owned clock barrier");
    }

    pub(super) async fn entered(&self) {
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), self.entered.notified())
            .await
            .expect("original clock reached selected boundary");
    }

    pub(super) async fn calls_reached(&self, count: usize) {
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), async {
            while self.calls.load(Ordering::SeqCst) < count {
                self.changed.notified().await;
            }
        })
        .await
        .expect("original clock reached expected sample count");
    }
}

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let call = self.calls.fetch_add(/*val*/ 1, Ordering::SeqCst) + 1;
        self.changed.notify_one();
        if call == self.block_at.load(Ordering::SeqCst) {
            self.entered.notify_one();
            self.release
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .recv_timeout(Duration::from_secs(/*secs*/ 5))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        // Like the original protected owner, sample AFTER any controlled I/O.
        Ok(self.now.load(Ordering::SeqCst))
    }
}

pub(super) struct Security {
    pub(super) authority: FinalUseAuthority,
    pub(super) signed: SignedFinalUseGrant,
    pub(super) clock: Arc<Clock>,
    _directory: tempfile::TempDir,
}

impl Security {
    pub(super) fn state_directory(&self) -> &std::path::Path {
        self._directory.path()
    }

    pub(super) fn new(
        binding: FinalUseBinding,
        label: &str,
        clock: Arc<Clock>,
        expiry: u64,
    ) -> Self {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let signed = signed_grant(binding, label, expiry);
        let directory = tempfile::tempdir().expect("private original authority");
        std::fs::set_permissions(
            directory.path(),
            std::fs::Permissions::from_mode(/*mode*/ 0o700),
        )
        .expect("private fixture state");
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
            clock.clone(),
        )
        .expect("original owner with explicit test clock");
        clock.reset_calls();
        Self {
            authority,
            signed,
            clock,
            _directory: directory,
        }
    }
}

pub(super) fn signed_grant(
    binding: FinalUseBinding,
    label: &str,
    expiry: u64,
) -> SignedFinalUseGrant {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let nonce = format!(
        "explicit-clock-fixture:{label}:{}",
        NEXT_TEST_NONCE.fetch_add(/*val*/ 1, Ordering::SeqCst)
    );
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: label.into(),
        nonce: digest_bytes(&Sha256Digest::for_bytes(nonce.as_bytes())),
        binding,
        not_before_unix_ms: 900,
        expires_at_unix_ms: expiry,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("explicit test grant bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}
