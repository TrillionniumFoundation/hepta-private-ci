//! Private durable file provider fixture. This explicitly controlled adapter
//! claims no production provider attestation, host permission or output ABI.

use codex_hepta_contracts::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

pub(super) const COMPLETE: usize = 0;
pub(super) const UNKNOWN: usize = 1;
pub(super) const HOLD_AFTER_PERSIST: usize = 2;
pub(super) const BEFORE_CONTACT: usize = 3;
pub(super) const WRONG_PAYLOAD: usize = 4;
pub(super) const RELEASE_MATCHING_ACK: usize = 5;
pub(super) const RELEASE_CONTRADICTORY_ACK: usize = 6;

#[derive(Clone)]
pub(super) struct FileProvider {
    root: PathBuf,
    pub(super) dispatches: Arc<AtomicUsize>,
    pub(super) lookups: Arc<AtomicUsize>,
    pub(super) dispatch_mode: Arc<AtomicUsize>,
    pub(super) lookup_mode: Arc<AtomicUsize>,
    pub(super) entered: Arc<Notify>,
    pub(super) release: Arc<Notify>,
}

impl FileProvider {
    pub(super) fn new(parent: &Path) -> Self {
        let root = parent.join("explicit-test-provider");
        std::fs::create_dir(&root).expect("private fixture provider");
        Self {
            root,
            dispatches: Arc::new(AtomicUsize::new(0)),
            lookups: Arc::new(AtomicUsize::new(0)),
            dispatch_mode: Arc::new(AtomicUsize::new(COMPLETE)),
            lookup_mode: Arc::new(AtomicUsize::new(COMPLETE)),
            entered: Arc::new(Notify::new()),
            release: Arc::new(Notify::new()),
        }
    }

    pub(super) fn payload(&self) -> Vec<u8> {
        std::fs::read(self.root.join("effect-payload")).expect("actual fixture effect bytes")
    }

    fn persist(
        &self,
        intent: &ProviderEffectIntent,
        bytes: &[u8],
    ) -> std::io::Result<ProviderEffectAck> {
        if Sha256Digest::for_bytes(bytes) != intent.payload_sha256 {
            return Err(std::io::Error::other("fixture exact payload mismatch"));
        }
        let ack = ProviderEffectAck::new(
            intent.key.clone(),
            intent.payload_sha256.clone(),
            Sha256Digest::for_bytes(b"explicit-test-file-occurrence"),
            ProviderEffectAckStatus::Completed,
        );
        let payload_path = self.root.join("effect-payload");
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&payload_path)
        {
            Ok(mut file) => {
                file.write_all(bytes)?;
                file.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if std::fs::read(&payload_path)? != bytes {
                    return Err(std::io::Error::other("fixture occurrence payload conflict"));
                }
            }
            Err(error) => return Err(error),
        }
        let encoded = serde_json::to_vec(&ack).map_err(std::io::Error::other)?;
        let receipt_path = self.root.join("receipt.json");
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&receipt_path)
        {
            Ok(mut file) => {
                file.write_all(&encoded)?;
                file.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if std::fs::read(&receipt_path)? != encoded {
                    return Err(std::io::Error::other(
                        "fixture occurrence identity conflict",
                    ));
                }
            }
            Err(error) => return Err(error),
        }
        File::open(&self.root)?.sync_all()?;
        Ok(ack)
    }
}

impl ProviderEffectAdapter for FileProvider {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "fixture_requires_exact_payload".into(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        bytes: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async move {
            self.dispatches.fetch_add(1, Ordering::SeqCst);
            let mode = self.dispatch_mode.load(Ordering::SeqCst);
            if mode == BEFORE_CONTACT {
                return ProviderEffectDispatch::NotDispatched {
                    reason_code: "explicit_fixture_before_contact".into(),
                };
            }
            let Ok(ack) = self.persist(intent, bytes) else {
                return ProviderEffectDispatch::Unknown;
            };
            self.entered.notify_one();
            match mode {
                UNKNOWN => ProviderEffectDispatch::Unknown,
                HOLD_AFTER_PERSIST => {
                    std::future::pending::<()>().await;
                    ProviderEffectDispatch::Unknown
                }
                RELEASE_MATCHING_ACK | RELEASE_CONTRADICTORY_ACK => {
                    self.release.notified().await;
                    let mut late = ack;
                    if mode == RELEASE_CONTRADICTORY_ACK {
                        // Alter only the late return, never the retained lookup receipt.
                        late.status = ProviderEffectAckStatus::Rejected;
                    }
                    ProviderEffectDispatch::Ack(late)
                }
                _ => ProviderEffectDispatch::Ack(ack),
            }
        })
    }

    fn lookup<'a>(
        &'a self,
        _: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async { ProviderEffectLookup::Unknown })
    }

    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(async move {
            self.lookups.fetch_add(1, Ordering::SeqCst);
            let mode = self.lookup_mode.load(Ordering::SeqCst);
            if mode == UNKNOWN {
                return ProviderEffectLookup::Unknown;
            }
            let bytes = match std::fs::read(self.root.join("receipt.json")) {
                Ok(bytes) => bytes,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    return ProviderEffectLookup::NotFound;
                }
                Err(_) => return ProviderEffectLookup::Unknown,
            };
            let Ok(mut ack) = serde_json::from_slice::<ProviderEffectAck>(&bytes) else {
                return ProviderEffectLookup::Unknown;
            };
            if ack.validate_for(intent).is_err() {
                return ProviderEffectLookup::Unknown;
            }
            if mode == WRONG_PAYLOAD {
                ack.payload_sha256 = Sha256Digest::for_bytes(b"malformed fixture receipt");
            }
            ProviderEffectLookup::Ack(ack)
        })
    }
}
