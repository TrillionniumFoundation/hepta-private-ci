use std::fs;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

fn file(root: &Path, name: &str) -> std::io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(root.join(name))
}

fn witness(root: &Path, binding: Digest32) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(root, "witness")?,
        JournalScope {
            scope_digest: binding,
            objective_digest: Digest32::of_bytes(b"objective"),
        },
        Generation::new(1)?,
        /*max_records*/ 8,
    )?)
}

#[tokio::test]
async fn historical_delivery_cancelled_claim_cold_reopen_never_redispatches() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    fs::write(root.path().join("journal"), [])?;
    fs::write(root.path().join("witness"), [])?;
    let binding = Digest32::of_bytes(b"historical-delivery");
    let key = ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("actual-claim")?,
        binding_digest: binding,
    };
    let mut owner = LearningOwnerJournalV1::create(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let (entered, observed) = tokio::sync::oneshot::channel();
    {
        let dispatch = owner.commit_original_historical_delivery(&key, || async {
            entered
                .send(())
                .map_err(|_| Error::Binding("claim observer closed"))?;
            std::future::pending::<Result<Vec<u8>, Error>>().await
        });
        tokio::pin!(dispatch);
        tokio::select! {
            result = &mut dispatch => anyhow::bail!("pending claim completed: {result:?}"),
            result = observed => result?,
        }
    }
    let claimed = fs::read(root.path().join("journal"))?;
    let retained = fs::read(root.path().join("witness"))?;
    drop(owner);
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let mut called = false;
    let result = reopened
        .commit_original_historical_delivery(&key, || async {
            called = true;
            Ok(b"replacement".to_vec())
        })
        .await;
    assert!(matches!(result, Err(Error::Pending)));
    assert!(!called);
    assert!(matches!(reopened.read(&key), Err(Error::Pending)));
    assert_eq!(fs::read(root.path().join("journal"))?, claimed);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    Ok(())
}

#[tokio::test]
async fn historical_delivery_completed_claim_cold_reopen_returns_exact_head() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    fs::write(root.path().join("journal"), [])?;
    fs::write(root.path().join("witness"), [])?;
    let binding = Digest32::of_bytes(b"historical-completed-delivery");
    let key = ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("original-head")?,
        binding_digest: binding,
    };
    let original = Digest32::of_bytes(b"root-complete-head")
        .as_array()
        .to_vec();
    let mut owner = LearningOwnerJournalV1::create(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    assert_eq!(
        owner
            .commit_original_historical_delivery(&key, || async { Ok(original.clone()) })
            .await?,
        original
    );
    drop(owner);
    let saved = fs::read(root.path().join("journal"))?;
    let retained = fs::read(root.path().join("witness"))?;
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let mut called = false;
    assert_eq!(
        reopened
            .commit_original_historical_delivery(&key, || async {
                called = true;
                Ok(b"replacement".to_vec())
            })
            .await?,
        original
    );
    assert!(!called);
    assert_eq!(fs::read(root.path().join("journal"))?, saved);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    Ok(())
}

#[tokio::test]
async fn historical_prepared_claim_drop_before_dispatch_cold_reopen_stays_pending()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    fs::write(root.path().join("journal"), [])?;
    fs::write(root.path().join("witness"), [])?;
    let binding = Digest32::of_bytes(b"historical-prepared-claim-drop");
    let key = ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("exact-prepared-claim")?,
        binding_digest: binding,
    };
    let mut owner = LearningOwnerJournalV1::create(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let preparation = owner.prepare_original_historical_delivery(&key)?;
    assert!(matches!(
        preparation,
        OriginalHistoricalDeliveryPreparationV1::Claimed(_)
    ));
    // The synchronous source postcheck may reject before dispatch begins.
    // Drop only the actual claim capability; never erase or complete Pending.
    drop(preparation);
    let claimed = fs::read(root.path().join("journal"))?;
    let retained = fs::read(root.path().join("witness"))?;
    assert!(matches!(owner.read(&key), Err(Error::Pending)));
    drop(owner);
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let mut called = false;
    let result = reopened
        .commit_original_historical_delivery(&key, || async {
            called = true;
            Ok(b"forbidden-redispatch".to_vec())
        })
        .await;
    assert!(matches!(result, Err(Error::Pending)));
    assert!(!called);
    assert_eq!(fs::read(root.path().join("journal"))?, claimed);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    Ok(())
}

#[test]
fn historical_prepared_completion_cold_reopen_returns_exact_key_and_bytes() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    fs::write(root.path().join("journal"), [])?;
    fs::write(root.path().join("witness"), [])?;
    let binding = Digest32::of_bytes(b"historical-prepared-completion");
    let key = ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("exact-completion")?,
        binding_digest: binding,
    };
    let original = Digest32::of_bytes(b"actual-completed-root-head")
        .as_array()
        .to_vec();
    let mut owner = LearningOwnerJournalV1::create(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    let claim = match owner.prepare_original_historical_delivery(&key)? {
        OriginalHistoricalDeliveryPreparationV1::Claimed(claim) => claim,
        OriginalHistoricalDeliveryPreparationV1::Completed(_) => {
            anyhow::bail!("fresh claim already completed")
        }
    };
    assert_eq!(
        claim.complete_original_historical_delivery(&original)?,
        original
    );
    let saved = fs::read(root.path().join("journal"))?;
    let retained = fs::read(root.path().join("witness"))?;
    drop(owner);
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    match reopened.prepare_original_historical_delivery(&key)? {
        OriginalHistoricalDeliveryPreparationV1::Completed(bytes) => assert_eq!(bytes, original),
        OriginalHistoricalDeliveryPreparationV1::Claimed(_) => {
            anyhow::bail!("completed operation acquired a new claim")
        }
    }
    assert_eq!(fs::read(root.path().join("journal"))?, saved);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    Ok(())
}

#[test]
fn historical_prepared_completion_full_witness_keeps_exact_append_for_recovery()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    fs::write(root.path().join("journal"), [])?;
    fs::write(root.path().join("witness"), [])?;
    let binding = Digest32::of_bytes(b"historical-prepared-witness-fault");
    let key = ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("exact-faulted-completion")?,
        binding_digest: binding,
    };
    let original = Digest32::of_bytes(b"actual-head-before-witness-failure")
        .as_array()
        .to_vec();
    // The original create anchor and the actual claim fill this file's two
    // records. Completion must append its real journal frame before witness
    // compare-and-swap refuses the third record; no mock error is substituted.
    let generation = Generation::new(1)?;
    let full_witness = || {
        FileAnchorWitnessStore::open(
            file(root.path(), "witness")?,
            JournalScope {
                scope_digest: binding,
                objective_digest: Digest32::of_bytes(b"objective"),
            },
            generation,
            2,
        )
    };
    let mut owner =
        LearningOwnerJournalV1::create(file(root.path(), "journal")?, full_witness()?, binding)?;
    let claim = match owner.prepare_original_historical_delivery(&key)? {
        OriginalHistoricalDeliveryPreparationV1::Claimed(claim) => claim,
        OriginalHistoricalDeliveryPreparationV1::Completed(_) => {
            anyhow::bail!("fresh claim already completed")
        }
    };
    let pending = fs::read(root.path().join("journal"))?;
    let retained = fs::read(root.path().join("witness"))?;
    assert!(matches!(
        claim.complete_original_historical_delivery(&original),
        Err(Error::CommitUncertain)
    ));
    let complete = fs::read(root.path().join("journal"))?;
    assert_ne!(complete, pending);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    assert!(matches!(owner.read(&key), Err(Error::CommitUncertain)));
    drop(owner);
    // Reopening the same full capacity cannot silently discard the completed
    // frame or claim recovery. The usual test helper's eight-record capacity
    // is used only after this genuine failed cold recovery has been observed.
    assert!(matches!(
        LearningOwnerJournalV1::recover(file(root.path(), "journal")?, full_witness()?, binding),
        Err(Error::CommitUncertain)
    ));
    assert_eq!(fs::read(root.path().join("journal"))?, complete);
    assert_eq!(fs::read(root.path().join("witness"))?, retained);
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    assert_eq!(reopened.read(&key)?, original);
    assert_eq!(fs::read(root.path().join("journal"))?, complete);
    let recovered = fs::read(root.path().join("witness"))?;
    assert_ne!(recovered, retained);
    drop(reopened);
    let mut reopened = LearningOwnerJournalV1::recover(
        file(root.path(), "journal")?,
        witness(root.path(), binding)?,
        binding,
    )?;
    assert_eq!(reopened.read(&key)?, original);
    assert_eq!(fs::read(root.path().join("journal"))?, complete);
    assert_eq!(fs::read(root.path().join("witness"))?, recovered);
    Ok(())
}
