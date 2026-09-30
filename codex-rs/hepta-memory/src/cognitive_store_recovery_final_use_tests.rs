use std::error::Error;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::CognitiveRecoveryError;
use super::CognitiveRecoveryRequirement;
use super::CognitiveStore;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;

struct FinalUseVerifier {
    calls: AtomicUsize,
    deny_publication: bool,
}

impl ProductionAuthorityVerifier for FinalUseVerifier {
    fn verify(&self, authority: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        if &authority.agent_id != owner || (self.deny_publication && call > 0) {
            return Err("authority revoked after recovery preflight".to_string());
        }
        Ok(())
    }
}

fn authority(owner: &AgentId) -> Result<ProductionAuthorityLease, Box<dyn Error>> {
    Ok(ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"final-publication-regression-grant"),
        7,
        11,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(b"final-publication-test-token".to_vec())?,
    )?)
}

#[tokio::test]
async fn revoked_at_final_use_leaves_pointer_and_predecessor_unchanged()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?.join("fleet");
    std::fs::create_dir(&root)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cf61")?;
    let layout = HeptaFleetRoot::parse(root)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let anchor = store.recovery_anchor().await?;
    let database = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);
    let before = std::fs::read(&database)?;
    let pointer = layout.cognitive_root().join(".cognitive-active-v1");
    let pointer_before = std::fs::read(&pointer).ok();
    let denied = FinalUseVerifier {
        calls: AtomicUsize::new(0),
        deny_publication: true,
    };
    let grant = authority(&owner)?;
    let result = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &grant,
        &denied,
    )
    .await;
    assert!(
        matches!(result, Err(CognitiveRecoveryError::AccessDenied(ref message))
        if message.contains("revoked after recovery preflight"))
    );
    assert_eq!(denied.calls.load(Ordering::SeqCst), 2);
    assert_eq!(std::fs::read(&pointer).ok(), pointer_before);
    assert_eq!(std::fs::read(&database)?, before);

    // Failed admission cleaned only the unpublished candidate. Retrying through
    // the SAME recovery owner still works; no ordinary-open fallback is used.
    let allowed = FinalUseVerifier {
        calls: AtomicUsize::new(0),
        deny_publication: false,
    };
    let recovered = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &grant,
        &allowed,
    )
    .await?;
    assert_eq!(allowed.calls.load(Ordering::SeqCst), 2);
    assert_eq!(recovered.recovery_anchor().await?, anchor);
    recovered.pool.close().await;
    Ok(())
}

#[tokio::test]
async fn measured_anchor_preserves_exact_cut_and_reports_distinct_durations()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?.join("fleet");
    std::fs::create_dir(&root)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cf62")?;
    let layout = HeptaFleetRoot::parse(root)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let before = store.recovery_anchor().await?;
    let (observed, acquisition, held) = store.recovery_anchor_measured().await?;
    assert_eq!(before, observed);
    assert!(acquisition.checked_add(held).is_some());
    assert!(!held.is_zero());
    assert_eq!(store.recovery_anchor().await?, before);
    store.pool.close().await;
    Ok(())
}
