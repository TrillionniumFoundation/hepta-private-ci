use std::future::Future;
use std::future::pending;
use std::pin::Pin;
use std::sync::Arc;

use futures::stream::FuturesUnordered;
use futures::stream::StreamExt;

use tokio::task::JoinError;
use tokio::task::JoinSet;
use tracing::warn;

pub(crate) struct ConnectionCleanupTasks {
    tasks: JoinSet<()>,
    original: Option<Arc<crate::OriginalAppServerOwnerCustody>>,
    original_waiters: FuturesUnordered<OriginalCleanupWaiter>,
}

type OriginalCleanupWaiter = Pin<
    Box<
        dyn Future<Output = Result<(), crate::original_owned_shutdown::OriginalAppServerFailure>>
            + Send,
    >,
>;

impl ConnectionCleanupTasks {
    pub(crate) fn new_original(original: Arc<crate::OriginalAppServerOwnerCustody>) -> Self {
        Self {
            original: Some(original),
            ..Self::new()
        }
    }

    pub(crate) fn new() -> Self {
        Self {
            tasks: JoinSet::new(),
            original: None,
            original_waiters: FuturesUnordered::new(),
        }
    }

    pub(crate) fn spawn(&mut self, future: impl Future<Output = ()> + Send + 'static) {
        if let Some(original) = &self.original {
            let job = crate::OriginalAppServerOwnerCustody::retain_original_task(
                original,
                crate::original_owned_shutdown::OriginalAppServerTaskKind::ConnectionCleanup,
                tokio::spawn(future),
            );
            self.original_waiters.push(Box::pin(async move {
                crate::original_owned_shutdown::OriginalAppServerJob::join_original(&job).await
            }));
            return;
        }
        self.tasks.spawn(future);
    }

    pub(crate) async fn reap_next(&mut self) {
        if let Some(original) = &self.original {
            if self.original_waiters.is_empty() {
                pending::<()>().await;
            }
            if let Some(Err(error)) = self.original_waiters.next().await {
                crate::OriginalAppServerOwnerCustody::record_original_failure(
                    original,
                    error.to_io(),
                );
            }
            return;
        }
        if self.tasks.is_empty() {
            pending::<()>().await;
        }
        if let Some(result) = self.tasks.join_next().await {
            log_cleanup_result(result);
        }
    }

    pub(crate) async fn drain(&mut self) {
        if let Some(original) = &self.original {
            while let Some(result) = self.original_waiters.next().await {
                if let Err(error) = result {
                    crate::OriginalAppServerOwnerCustody::record_original_failure(
                        original,
                        error.to_io(),
                    );
                }
            }
            return;
        }
        while let Some(result) = self.tasks.join_next().await {
            log_cleanup_result(result);
        }
    }

    pub(crate) fn abort(&mut self) {
        if let Some(original) = &self.original {
            crate::OriginalAppServerOwnerCustody::record_original_failure(
                original,
                std::io::Error::other("original connection cleanup requested forced abort"),
            );
            crate::OriginalAppServerOwnerCustody::request_stop(original);
            return;
        }
        self.tasks.abort_all();
    }
}

fn log_cleanup_result(result: Result<(), JoinError>) {
    if let Err(err) = result
        && !err.is_cancelled()
    {
        warn!("connection cleanup task failed: {err}");
    }
}
