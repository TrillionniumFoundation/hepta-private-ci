//! Single-call CURRENT mechanics with the actual ordinary A/C publication.
//! The original Source/Cell read mechanisms and the Observer's unchanged 500 ms
//! transport test remain the complete-path and performance acceptance tests.

use super::*;
use pretty_assertions::assert_eq;

use crate::circuit_feature_current::original_learning_read_fixture::current_slots as slot_fixture;

#[tokio::test]
async fn published_current_last_original_slot_rejects_actual_withdrawal() -> anyhow::Result<()> {
    let mut f = Box::pin(SelectionFixture::ready()).await?;
    let original = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    let source_before = owner_bytes(&f.original.session)?;
    let pending = slot_fixture::pending_final_reads(&f.original.session.cell)?;
    // Both calls already performed their first physical CURRENT check. The
    // original publication is withdrawn before their original final slot.
    f.original.version.withdraw()?;
    let public_error = f
        .original
        .session
        .cell
        .read_learning_selection(&original)
        .unwrap_err();
    for call in pending {
        let final_error = call.finish().expect_err("last actual CURRENT must refuse");
        assert_eq!(
            std::mem::discriminant(&final_error),
            std::mem::discriminant(&public_error),
        );
        assert_eq!(final_error.to_string(), public_error.to_string());
    }
    assert_eq!(owner_bytes(&f.original.session)?, source_before);
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn published_current_call_rejects_other_original_incomplete_and_reuse() -> anyhow::Result<()>
{
    let mut f = Box::pin(SelectionFixture::ready()).await?;
    let mut other = Box::pin(SelectionFixture::ready()).await?;
    let before = owner_bytes(&f.original.session)?;
    let other_before = owner_bytes(&other.original.session)?;
    slot_fixture::reject_wrong_original_and_reuse(
        &f.original.session.cell,
        &other.original.session.cell,
    )?;
    assert_eq!(owner_bytes(&f.original.session)?, before);
    assert_eq!(owner_bytes(&other.original.session)?, other_before);
    f.original.session.stop().await?;
    other.original.session.stop().await?;
    Ok(())
}
