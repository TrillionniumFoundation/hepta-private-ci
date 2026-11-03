use super::QueuePersistedBindingObservation;
use anyhow::Context;
use crate::QueuedClientBindingConflict;
use crate::QueuedClientBindingFinalizeMode;
use crate::QueuedClientBindingFinalizeOutcome;
use crate::QueuedClientBindingFinalizeRequest;
use crate::QueuedClientBindingReserveOutcome;
use crate::QueuedClientDispatchClaimOutcome;
use crate::QueuedUserSubmissionRecord;
use crate::StateRuntime;
use crate::runtime::test_support::test_thread_metadata;
use crate::runtime::test_support::unique_temp_dir;
use codex_protocol::ThreadId;
use codex_utils_absolute_path::test_support::PathExt;
use std::sync::Arc;

struct Fixture {
    runtime: Arc<StateRuntime>,
    thread_id: ThreadId,
    digest: String,
    record: QueuedUserSubmissionRecord,
}

const CLIENT_ID: &str = "persisted-observation-client";

fn payload(client_id: &str) -> String {
    format!(
        r#"{{"UserInput":{{"content":[{{"Text":{{"text":"original input","text_elements":[]}}}}],"client_id":"{client_id}"}}}}"#,
    )
}

impl Fixture {
    async fn new() -> anyhow::Result<Self> {
        let home = unique_temp_dir();
        let runtime = StateRuntime::init(
            crate::SqliteConfig::new_for_testing(home.as_path().abs()),
            "test-provider".to_string(),
        )
        .await?;
        let thread_id = ThreadId::new();
        let metadata = test_thread_metadata(home.as_path(), thread_id, home.clone());
        runtime.upsert_thread(&metadata).await?;
        let digest = "a".repeat(64);
        let payload = payload(CLIENT_ID);
        let QueuedClientBindingReserveOutcome::Reserved(lease) = runtime
            .thread_queue()
            .reserve_client_binding(thread_id, CLIENT_ID, &digest, &payload)
            .await?
        else {
            anyhow::bail!("original new client did not reserve");
        };
        let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = runtime
            .thread_queue()
            .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                thread_id,
                client_id: CLIENT_ID.to_string(),
                payload_sha256: digest.clone(),
                payload_json: payload,
                lease,
                mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
                observed_turn_id: None,
                runtime_capacity: None,
            })
            .await?
        else {
            anyhow::bail!("original reservation did not create one queue row");
        };
        Ok(Self {
            runtime,
            thread_id,
            digest,
            record,
        })
    }

    async fn complete(&self) -> anyhow::Result<()> {
        let queue = self.runtime.thread_queue();
        let process_lock = queue
            .try_acquire_client_dispatch_lock(self.thread_id, CLIENT_ID, &self.digest)?
            .context("original queue dispatch lock unavailable")?;
        let QueuedClientDispatchClaimOutcome::Acquired(lease) = queue
            .claim_client_binding_dispatch(&process_lock, &self.record.id, "owner", 100, 200)
            .await?
        else {
            anyhow::bail!("original dispatch was not acquired");
        };
        let lease = queue
            .authorize_client_binding_dispatch(&process_lock, &lease, 101, 201)
            .await?;
        queue
            .complete_client_binding_dispatch(&process_lock, &lease, "original-turn")
            .await
    }

    async fn observe(&self) -> anyhow::Result<Option<QueuePersistedBindingObservation>> {
        self.runtime
            .thread_queue()
            .observe_persisted_client_binding(self.thread_id, CLIENT_ID, &self.digest)
            .await
    }

    async fn versions(&self) -> anyhow::Result<(i64, Vec<(ThreadId, i64)>, i64)> {
        let queue = self.runtime.thread_queue();
        // The first change_version call detaches a pool connection. Finish
        // the auxiliary pool reads (including replacement-connection setup)
        // before sampling the stable observer's baseline. Candidate reads run
        // only after this complete snapshot; their commits remain detectable.
        queue.change_version().await?;
        let revisions = queue.changes_since(0, &[self.thread_id]).await?;
        let bindings = sqlx::query_scalar("SELECT COUNT(*) FROM queued_client_bindings")
            .fetch_one(queue.pool.as_ref())
            .await?;
        let version = queue.change_version().await?;
        Ok((version, revisions, bindings))
    }
}

fn require_conflict<T>(result: anyhow::Result<T>) -> anyhow::Result<()> {
    let error = result.err().context("expected original binding conflict")?;
    anyhow::ensure!(
        error.downcast_ref::<QueuedClientBindingConflict>().is_some(),
        "unexpected error instead of binding conflict: {error:#}"
    );
    Ok(())
}

#[tokio::test]
async fn persisted_observation_and_revalidation_are_read_only_after_real_dispatch()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    fixture.complete().await?;
    let before = fixture.versions().await?;
    let observation = fixture.observe().await?.context("completed binding missing")?;
    pretty_assertions::assert_eq!(observation.thread_id, fixture.thread_id);
    pretty_assertions::assert_eq!(observation.client_id, CLIENT_ID);
    pretty_assertions::assert_eq!(observation.payload_sha256, fixture.digest);
    pretty_assertions::assert_eq!(observation.turn_id, "original-turn");
    assert!(observation.revision > 1);
    fixture
        .runtime
        .thread_queue()
        .revalidate_persisted_client_binding(&observation)
        .await?;
    let queued_item_id: Option<String> = sqlx::query_scalar(
        "SELECT queued_item_id FROM queued_client_bindings
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(fixture.thread_id.to_string())
    .bind(CLIENT_ID)
    .fetch_one(fixture.runtime.thread_queue().pool.as_ref())
    .await?;
    assert!(queued_item_id.is_none(), "old queue id belongs to Core provenance");
    assert!(
        fixture
            .runtime
            .thread_queue()
            .list_page(fixture.thread_id, 0, 10)
            .await?
            .is_empty()
    );
    pretty_assertions::assert_eq!(fixture.versions().await?, before);

    // Positive control: the same fixed observer must detect an actual original
    // queue commit after the read-only checks, even without a new queue item.
    let control = "read-only-observation-write-control";
    let reserved = fixture.runtime.thread_queue().reserve_client_binding(
        fixture.thread_id, control, &fixture.digest, &payload(control),
    ).await?;
    assert!(matches!(reserved, QueuedClientBindingReserveOutcome::Reserved(_)));
    let after_write = fixture.versions().await?;
    pretty_assertions::assert_ne!(after_write.0, before.0,
        "the read-only witness must still detect a real queue-database commit");
    pretty_assertions::assert_eq!(after_write.2, before.2 + 1);
    Ok(())
}

#[tokio::test]
async fn missing_unfinished_cancelled_and_wrong_payload_never_produce_completion()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let queue = fixture.runtime.thread_queue();
    let before = fixture.versions().await?;
    assert!(
        queue
            .observe_persisted_client_binding(fixture.thread_id, "missing", &fixture.digest)
            .await?
            .is_none()
    );
    pretty_assertions::assert_eq!(fixture.versions().await?, before);
    require_conflict(fixture.observe().await)?;
    require_conflict(
        queue
            .observe_persisted_client_binding(fixture.thread_id, CLIENT_ID, &"b".repeat(64))
            .await,
    )?;
    queue
        .reserve_client_binding(
            fixture.thread_id,
            "reserved",
            &fixture.digest,
            &payload("reserved"),
        )
        .await?;
    require_conflict(
        queue
            .observe_persisted_client_binding(fixture.thread_id, "reserved", &fixture.digest)
            .await,
    )?;
    let process_lock = queue
        .try_acquire_client_dispatch_lock(fixture.thread_id, CLIENT_ID, &fixture.digest)?
        .context("original dispatch lock unavailable")?;
    let QueuedClientDispatchClaimOutcome::Acquired(lease) = queue
        .claim_client_binding_dispatch(&process_lock, &fixture.record.id, "owner", 100, 200)
        .await?
    else {
        anyhow::bail!("original dispatch was not acquired");
    };
    require_conflict(fixture.observe().await)?;
    queue
        .release_client_binding_dispatch(&process_lock, &lease)
        .await?;
    drop(process_lock);
    assert!(queue.delete(fixture.thread_id, &fixture.record.id).await?);
    require_conflict(fixture.observe().await)?;
    let before = fixture.versions().await?;
    require_conflict(
        queue
            .observe_persisted_client_binding(fixture.thread_id, "", &fixture.digest)
            .await,
    )?;
    require_conflict(
        queue
            .observe_persisted_client_binding(fixture.thread_id, CLIENT_ID, "invalid")
            .await,
    )?;
    pretty_assertions::assert_eq!(fixture.versions().await?, before);
    Ok(())
}

#[tokio::test]
async fn revalidation_rejects_changed_tuple_revision_and_deleted_original_binding()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    fixture.complete().await?;
    let queue = fixture.runtime.thread_queue();
    let observation = fixture.observe().await?.context("completed binding missing")?;
    let mut candidates = Vec::new();
    let mut changed = observation.clone();
    changed.thread_id = ThreadId::new();
    candidates.push(changed);
    let mut changed = observation.clone();
    changed.client_id = "another-client".to_string();
    candidates.push(changed);
    let mut changed = observation.clone();
    changed.payload_sha256 = "b".repeat(64);
    candidates.push(changed);
    let mut changed = observation.clone();
    changed.turn_id = "another-turn".to_string();
    candidates.push(changed);
    let mut changed = observation.clone();
    changed.revision += 1;
    candidates.push(changed);
    for candidate in candidates {
        require_conflict(queue.revalidate_persisted_client_binding(&candidate).await)?;
    }

    // Change only the original row's revision; identical content is insufficient.
    sqlx::query(
        "UPDATE queued_client_bindings SET revision = revision + 1
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(fixture.thread_id.to_string())
    .bind(CLIENT_ID)
    .execute(queue.pool.as_ref())
    .await?;
    require_conflict(queue.revalidate_persisted_client_binding(&observation).await)?;
    let current = fixture.observe().await?.context("original binding missing")?;
    pretty_assertions::assert_eq!(current.revision, observation.revision + 1);
    queue.revalidate_persisted_client_binding(&current).await?;

    // Use the original durable hard-delete protocol, not a new test tombstone.
    queue
        .seal_thread_queues_for_deletion(&[fixture.thread_id])
        .await?;
    require_conflict(queue.revalidate_persisted_client_binding(&current).await)?;
    require_conflict(fixture.observe().await)?;
    Ok(())
}

#[tokio::test]
async fn persisted_observation_survives_original_store_reopen() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    fixture.complete().await?;
    let observation = fixture.observe().await?.context("completed binding missing")?;
    let sqlite = fixture.runtime.sqlite().clone();
    drop(fixture);
    let reopened = StateRuntime::init(sqlite, "test-provider".to_string()).await?;
    let observed = reopened
        .thread_queue()
        .observe_persisted_client_binding(
            observation.thread_id,
            &observation.client_id,
            &observation.payload_sha256,
        )
        .await?
        .context("reopened original binding missing")?;
    pretty_assertions::assert_eq!(observed, observation);
    reopened
        .thread_queue()
        .revalidate_persisted_client_binding(&observation)
        .await?;
    Ok(())
}
