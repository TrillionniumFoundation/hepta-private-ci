//! Fixed original Current publisher retained at protected-store binding.

use crate::CheckpointDiagnostics;
use crate::CognitiveRecoveryAnchor;
use crate::ObjectiveSenderCheckpointError;
use crate::ObjectiveSenderWriterFence;
use crate::cognitive_checkpoint::CognitiveCheckpointTransport;
use crate::cognitive_checkpoint::ProtectedCognitiveCheckpoint;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

type Publication = Pin<
    Box<
        dyn Future<Output = Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError>> + Send,
    >,
>;
type Publish = dyn Fn(
        CognitiveRecoveryAnchor,
        ObjectiveSenderWriterFence,
        Arc<CheckpointDiagnostics>,
    ) -> Publication
    + Send
    + Sync;

/// Type erasure retains the one protected coordinator. Runtime callers cannot
/// install an alternate publisher or substitute a locally calculated receipt.
#[derive(Clone)]
pub(crate) struct BoundCurrentPublisher {
    publish: Arc<Publish>,
    pub(crate) deadline: Duration,
}

impl BoundCurrentPublisher {
    pub(super) fn new<T: CognitiveCheckpointTransport + 'static>(
        coordinator: Arc<ProtectedCognitiveCheckpoint<T>>,
        deadline: Duration,
    ) -> Self {
        Self {
            publish: Arc::new(move |cut, writer, diagnostics| {
                let coordinator = Arc::clone(&coordinator);
                Box::pin(async move {
                    coordinator
                        .acknowledge_diagnosed(&cut, &writer, &diagnostics)
                        .await
                })
            }),
            deadline,
        }
    }

    pub(crate) fn acknowledge(
        &self,
        cut: CognitiveRecoveryAnchor,
        writer: ObjectiveSenderWriterFence,
        diagnostics: Arc<CheckpointDiagnostics>,
    ) -> Publication {
        (self.publish)(cut, writer, diagnostics)
    }
}
