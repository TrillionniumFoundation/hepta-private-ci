//! Host-selected model entry with the existing bounded Responses observations.

use std::future::Future;

use anyhow::Result;

use crate::ModelRequest;
use crate::ObservedModelCompletion;
use crate::ResponsesModel;
use crate::ResponsesStream;

/// Lets a host wrap model entry without replacing the Responses parser.
///
/// `open` is called for one already checkpointed request. Implementations must
/// preserve its operation and exact body, apply any host-owned entry checks,
/// and never retry an ambiguous POST. `reconcile` observes only the original
/// provider response; it must not dispatch another model request.
///
/// This port does not issue authority or make a checkpoint an execution grant.
/// Production wrappers remain responsible for consuming their existing owner's
/// final-use capability at the concrete effect entry. The observation types
/// deliberately retain their restricted constructors.
pub trait ModelPort: Send + Sync {
    fn open(&self, request: &ModelRequest) -> impl Future<Output = Result<ResponsesStream>> + Send;

    fn reconcile(
        &self,
        request: &ModelRequest,
        response_id: &str,
    ) -> impl Future<Output = Result<Option<ObservedModelCompletion>>> + Send;
}

impl ModelPort for ResponsesModel {
    async fn open(&self, request: &ModelRequest) -> Result<ResponsesStream> {
        ResponsesModel::open(self, request).await
    }

    async fn reconcile(
        &self,
        request: &ModelRequest,
        response_id: &str,
    ) -> Result<Option<ObservedModelCompletion>> {
        ResponsesModel::reconcile(self, request, response_id).await
    }
}
