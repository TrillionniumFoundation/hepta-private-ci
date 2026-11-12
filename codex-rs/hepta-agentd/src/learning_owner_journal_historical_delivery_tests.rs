use std::fs;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::Generation;
use codex_hepta_neuron::JournalScope;
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
