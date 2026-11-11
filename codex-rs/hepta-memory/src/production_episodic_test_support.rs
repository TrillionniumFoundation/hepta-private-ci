use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveStore;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionDurableWriter;
use crate::cognitive_test_support;

pub(super) struct Fixture {
    pub(super) directory: TempDir,
    pub(super) store: CognitiveStore,
    pub(super) writer: Arc<ProductionDurableWriter>,
    pub(super) authority: ProductionAuthorityLease,
    pub(super) verifier: Arc<dyn ProductionAuthorityVerifier>,
    pub(super) live: Arc<AtomicBool>,
    pub(super) access: CognitiveAccess,
}

pub(super) async fn fixture() -> Result<Fixture, Box<dyn std::error::Error>> {
    let directory = TempDir::new()?;
    let owner = cognitive_test_support::agent_id(/*suffix*/ 80);
    let layout = cognitive_test_support::layout(&directory, &owner);
    let store = CognitiveStore::open(&layout).await?;
    let grant = Sha256Digest::for_bytes(b"episodic-fixture-original-writer-grant");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(), grant.clone(), /*authority_epoch*/ 1, /*owner_epoch*/ 1,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 600,
        ProductionAuthorityToken::from_verified_bytes(b"episodic-fixture-original-writer-token".to_vec())?,
    )?;
    let live = Arc::new(AtomicBool::new(true));
    let live_for_verifier = Arc::clone(&live);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| {
            if live_for_verifier.load(Ordering::SeqCst) && lease.agent_id == *expected && lease.grant_digest == grant {
                Ok(())
            } else {
                Err("original writer authority rejected".to_string())
            }
        },
    );
    let writer = Arc::new(ProductionDurableWriter::open_with_live_verifier(
        store.clone(), authority.clone(), Arc::clone(&verifier), "episodic-original-writer", /*generation*/ 1,
    ).await?);
    Ok(Fixture { directory, store, writer, authority, verifier, live, access: CognitiveAccess::agent_private(owner) })
}
