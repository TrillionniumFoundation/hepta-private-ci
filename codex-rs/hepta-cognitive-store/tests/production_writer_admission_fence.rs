#![cfg(feature = "qualification-cognitive-write")]

use std::error::Error;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_cognitive_store::{
    CognitiveRecoveryRequirement, DurableCognitiveStore, ProductionAuthorityLease,
    ProductionAuthorityToken, ProductionAuthorityVerifier, ProductionDurableWriter,
    ProductionWriterError,
};
use codex_hepta_contracts::{AgentId, Sha256Digest};
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

struct AllowVerifier;

impl ProductionAuthorityVerifier for AllowVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id == expected_agent {
            Ok(())
        } else {
            Err("authority owner mismatch".to_string())
        }
    }
}

struct FailFinalVerifier {
    calls: AtomicUsize,
}

impl ProductionAuthorityVerifier for FailFinalVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id != expected_agent {
            return Err("authority owner mismatch".to_string());
        }
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if call == 1 {
            Ok(())
        } else {
            Err("injected final authority rejection".to_string())
        }
    }
}

#[tokio::test]
async fn failed_final_authority_recheck_closes_recovered_pool_before_fence_release(
) -> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let fleet = temp.path().canonicalize()?.join("fleet");
    std::fs::create_dir_all(&fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cf82")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);

    let seed = DurableCognitiveStore::open(&layout).await?;
    let initial = seed.recovery_anchor().await?;
    seed.close_for_recovery_handoff().await?;

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"writer-admission-fence-grant"),
        1,
        1,
        SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_secs()
            .checked_add(3600)
            .ok_or("authority expiry overflow")?,
        ProductionAuthorityToken::from_verified_bytes(
            b"writer-admission-fence-token".to_vec(),
        )?,
    )?;

    let recovered = DurableCognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&initial),
        &authority,
        &AllowVerifier,
    )
    .await?;

    let rejected = ProductionDurableWriter::open_with_live_verifier(
        recovered,
        authority.clone(),
        Arc::new(FailFinalVerifier {
            calls: AtomicUsize::new(0),
        }),
        "writer-admission-fence",
        1,
    )
    .await
    .expect_err("the final authority recheck must reject admission");
    assert!(matches!(
        rejected,
        ProductionWriterError::AuthorityRejected(_)
    ));

    // The failed admission must have awaited pool closure before releasing the
    // exclusive recovery fence. Immediate ordinary reopen is the regression:
    // it must not race leaked connections from the rejected generation.
    let observed = DurableCognitiveStore::open(&layout).await?;
    let current = observed.recovery_anchor().await?;
    observed.close_for_recovery_handoff().await?;
    assert_ne!(current, initial, "lease admission must remain durable");

    let recovered = DurableCognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        &authority,
        &AllowVerifier,
    )
    .await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        recovered,
        authority,
        Arc::new(AllowVerifier),
        "writer-admission-fence",
        1,
    )
    .await?;
    assert_eq!(writer.generation(), 1);
    writer.release().await?;
    Ok(())
}
