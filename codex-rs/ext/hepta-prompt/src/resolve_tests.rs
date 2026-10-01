use super::*;

use std::future::poll_fn;
use std::sync::atomic::AtomicUsize;
use std::task::Poll;
use std::time::Duration;

use tokio::sync::Notify;
use tokio::sync::Semaphore;

struct PreparationState {
    entries: AtomicUsize,
    active: AtomicUsize,
    maximum_active: AtomicUsize,
    entered: Notify,
    release: Semaphore,
}

impl Default for PreparationState {
    fn default() -> Self {
        Self {
            entries: AtomicUsize::default(),
            active: AtomicUsize::default(),
            maximum_active: AtomicUsize::default(),
            entered: Notify::default(),
            release: Semaphore::new(/*permits*/ 0),
        }
    }
}

struct ActivePreparation(Arc<PreparationState>);

impl Drop for ActivePreparation {
    fn drop(&mut self) {
        self.0.active.fetch_sub(1, Ordering::SeqCst);
    }
}

fn extension(
    state: &Arc<PreparationState>,
    result: Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError>,
) -> PromptRuntimeExtension {
    let state = Arc::clone(state);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-resolve-test",
        move |_request| {
            let state = Arc::clone(&state);
            let result = result.clone();
            Box::pin(async move {
                state.entries.fetch_add(1, Ordering::SeqCst);
                let active = state.active.fetch_add(1, Ordering::SeqCst) + 1;
                state.maximum_active.fetch_max(active, Ordering::SeqCst);
                let _active = ActivePreparation(Arc::clone(&state));
                state.entered.notify_one();
                let permit = state.release.acquire().await.map_err(|_| {
                    PromptRuntimeHostError::new("test_gate_closed", "preparation gate closed")
                })?;
                permit.forget();
                result
            })
        },
        |_record| Box::pin(async { Ok(()) }),
        |_record| Box::pin(async { Ok(()) }),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    PromptRuntimeExtension { host }
}

fn attachment() -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(
        StableId::new("compilation:resolve-test").unwrap_or_else(|error| panic!("id: {error}")),
        Digest32::of_bytes(b"attachment"),
        Digest32::of_bytes(b"payload"),
        "model:resolve-test",
        /*deadline_ms*/ u64::MAX,
        vec![
            PromptRuntimeDeveloperFragmentV1::new("Inspect the admitted evidence.")
                .unwrap_or_else(|error| panic!("fragment: {error}")),
        ],
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"))
}

async fn require_pending<F: Future>(mut future: Pin<&mut F>) {
    let pending = poll_fn(|context| Poll::Ready(future.as_mut().poll(context).is_pending())).await;
    assert!(
        pending,
        "blocked preparation must keep its resolver pending"
    );
}

fn require_result(
    result: ResolvedAttachment,
    expected: &Result<Option<PromptRuntimeAttachmentV1>, PromptRuntimeHostError>,
) {
    match (result, expected) {
        (ResolvedAttachment::Ready(actual), Ok(Some(expected))) => assert_eq!(&actual, expected),
        (ResolvedAttachment::None, Ok(None)) => {}
        (ResolvedAttachment::Failed(actual), Err(expected)) => assert_eq!(&actual, expected),
        _ => panic!("cached preparation differs from its host result"),
    }
}

#[tokio::test]
async fn concurrent_resolve_initializes_once_and_caches_ready_none_and_failure() {
    for expected in [
        Ok(Some(attachment())),
        Ok(None),
        Err(PromptRuntimeHostError::new(
            "test_failure",
            "bounded host failure",
        )),
    ] {
        let state = Arc::new(PreparationState::default());
        let extension = extension(&state, expected.clone());
        let turn = ExtensionData::new("turn:resolve-cache");
        let mut first = Box::pin(extension.resolve(
            "thread:resolve-cache".to_owned(),
            turn.level_id().to_owned(),
            /*model_context_window*/ Some(128_000),
            &turn,
        ));
        require_pending(first.as_mut()).await;
        tokio::time::timeout(Duration::from_secs(5), state.entered.notified())
            .await
            .unwrap_or_else(|error| panic!("initializer did not enter: {error}"));
        let mut second = Box::pin(extension.resolve(
            "thread:resolve-cache".to_owned(),
            turn.level_id().to_owned(),
            /*model_context_window*/ None,
            &turn,
        ));
        require_pending(second.as_mut()).await;
        assert_eq!(state.entries.load(Ordering::SeqCst), 1);
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
        state.release.add_permits(1);
        let (first, second) = tokio::time::timeout(Duration::from_secs(5), async {
            tokio::join!(first, second)
        })
        .await
        .unwrap_or_else(|error| panic!("concurrent resolution stalled: {error}"));
        require_result(first, &expected);
        require_result(second, &expected);
        let cached = tokio::time::timeout(
            Duration::from_secs(5),
            extension.resolve(
                "thread:resolve-cache".to_owned(),
                turn.level_id().to_owned(),
                /*model_context_window*/ None,
                &turn,
            ),
        )
        .await
        .unwrap_or_else(|error| panic!("cached resolution stalled: {error}"));
        require_result(cached, &expected);
        assert_eq!(state.entries.load(Ordering::SeqCst), 1);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
        assert_eq!(state.maximum_active.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn cancelled_initializer_allows_waiting_resolve_to_retry_without_overlap() {
    let state = Arc::new(PreparationState::default());
    let expected = Ok(Some(attachment()));
    let extension = extension(&state, expected.clone());
    let turn = ExtensionData::new("turn:resolve-cancel");
    let mut first = Box::pin(extension.resolve(
        "thread:resolve-cancel".to_owned(),
        turn.level_id().to_owned(),
        /*model_context_window*/ Some(128_000),
        &turn,
    ));
    require_pending(first.as_mut()).await;
    tokio::time::timeout(Duration::from_secs(5), state.entered.notified())
        .await
        .unwrap_or_else(|error| panic!("initial preparation did not enter: {error}"));
    let mut waiting = Box::pin(extension.resolve(
        "thread:resolve-cancel".to_owned(),
        turn.level_id().to_owned(),
        /*model_context_window*/ None,
        &turn,
    ));
    require_pending(waiting.as_mut()).await;
    assert_eq!(state.entries.load(Ordering::SeqCst), 1);
    drop(first);
    assert_eq!(state.active.load(Ordering::SeqCst), 0);
    require_pending(waiting.as_mut()).await;
    tokio::time::timeout(Duration::from_secs(5), state.entered.notified())
        .await
        .unwrap_or_else(|error| panic!("waiting resolver did not retry: {error}"));
    assert_eq!(state.entries.load(Ordering::SeqCst), 2);
    assert_eq!(state.active.load(Ordering::SeqCst), 1);
    state.release.add_permits(1);
    let resolved = tokio::time::timeout(Duration::from_secs(5), waiting)
        .await
        .unwrap_or_else(|error| panic!("retried resolution stalled: {error}"));
    require_result(resolved, &expected);
    let cached = tokio::time::timeout(
        Duration::from_secs(5),
        extension.resolve(
            "thread:resolve-cancel".to_owned(),
            turn.level_id().to_owned(),
            /*model_context_window*/ None,
            &turn,
        ),
    )
    .await
    .unwrap_or_else(|error| panic!("cached retry stalled: {error}"));
    require_result(cached, &expected);
    assert_eq!(state.entries.load(Ordering::SeqCst), 2);
    assert_eq!(state.active.load(Ordering::SeqCst), 0);
    assert_eq!(state.maximum_active.load(Ordering::SeqCst), 1);
}
