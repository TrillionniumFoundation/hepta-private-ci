//! Native test composition using the existing opaque Windows owner API.
//! The in-memory frontier is only a test fixture. It is not external durability,
//! a trusted clock attestation, or Windows power-loss qualification.

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::windows_private_owner::ParentAnchor;
use codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);
impl Drop for Directory {
    fn drop(&mut self) {
        for name in [
            "authority.json",
            "authority.next",
            "authority.claims",
            "authority.claims.next",
            "authority.lock",
        ] {
            let _ = std::fs::remove_file(self.0.join(name));
        }
        let _ = std::fs::remove_dir(&self.0);
    }
}

struct Frontier {
    value: Mutex<FinalUseFrontier>,
    // FinalUseAuthority drops its native store before its frontier Arc. Keep
    // cleanup with that Arc so every authority/token clone retains the root.
    _directory: Directory,
}
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _: &str) -> std::result::Result<FinalUseFrontier, AuthorityTrustError> {
        self.value
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
    fn compare_and_set(
        &self,
        _: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> std::result::Result<(), AuthorityTrustError> {
        let mut value = self
            .value
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if &*value != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *value = *next;
        Ok(())
    }
}

pub(crate) fn open_fresh(
    signer_id: String,
    verifying_key: [u8; 32],
    head: FinalUseRevocations,
    clock: Arc<dyn AuthorityClock>,
) -> Result<FinalUseAuthority> {
    let parent = PathBuf::from(format!(r"{}\", std::env::var("SystemDrive")?));
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
    let leaf = format!(
        "hepta-native-fixture-{}-{nonce}-{sequence}",
        std::process::id()
    );
    let directory = ParentAnchor::for_create_only(&parent)?.create_private_directory(&leaf)?;
    let frontier = Arc::new(Frontier {
        value: Mutex::new(FinalUseFrontier::for_initial_head(&head)?),
        _directory: Directory(parent.join(&leaf)),
    });
    Ok(FinalUseAuthority::open_windows_private_with_trust(
        PrivateStoreDirectory::Fresh(directory),
        signer_id,
        verifying_key,
        head,
        clock,
        frontier,
    )?)
}
