//! Explicit native product startup using the embedding's existing owners.
//!
//! The loader is trusted host code, not an ObjectiveStart request decoder. It
//! supplies already authorized owners and independently recovered writer state.
//! This module creates no owner store, issuer, grant, queue, or replacement run.
//! Loading and structural composition do not grant permission for an effect:
//! the original startup, admission, currentness, and FinalUse gates still apply.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use codex_arg0::Arg0DispatchPaths;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::AgentdNativeRuntimeConfig;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use crate::NativeHostedRuntimeConfig;

/// Complete, single-use composition for the signed canonical Objective route.
///
/// Each field is an existing owner or its explicit configuration. In
/// particular, `recovered_writer` must carry the independently verified
/// recovery attachment, and `operations` must name that same live writer,
/// registered FinalUse authority, and external grant provider. Those proofs
/// are checked by the original owners when this bundle is configured/attached.
/// This value is deliberately neither serializable nor cloneable.
pub struct AgentdCanonicalNativeCompositionV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    recovered_writer: Arc<AgentdProductionWriterHost>,
    operations: AgentdProductionOperationRuntimeConfig,
    native: AgentdNativeRuntimeConfig,
}

impl AgentdCanonicalNativeCompositionV1 {
    pub fn new(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        invocation_provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        recovered_writer: Arc<AgentdProductionWriterHost>,
        operations: AgentdProductionOperationRuntimeConfig,
        native: AgentdNativeRuntimeConfig,
    ) -> Result<Self, AgentdError> {
        if !matches!(
            &native.hosted_turn,
            Some(NativeHostedRuntimeConfig::CanonicalObjective { .. })
        ) {
            return Err(AgentdError::Invalid(
                "native product startup requires the original canonical Objective owner".to_owned(),
            ));
        }
        Ok(Self {
            runner,
            invocation_provider,
            recovered_writer,
            operations,
            native,
        })
    }

    /// Consume the complete bundle into the original daemon configuration.
    ///
    /// The caller selects AuthBus trust/replay files and the Objective profile
    /// on `config` before this call. Duplicate owners and missing prerequisites
    /// are errors; none are inferred from a model request or an ambient path.
    /// Runtime host probes and native target attachment happen only in `run`,
    /// after these original configuration gates have all succeeded.
    pub fn configure(self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        let config = config
            .with_intelligence_product_runner(self.runner)?
            .with_intelligence_invocation_provider(self.invocation_provider)?
            .with_production_writer_host(self.recovered_writer)?
            .with_production_operations(self.operations)?
            .with_native_runtime(self.native)?;
        config.validate_native_composition()?;
        Ok(config)
    }
}

pub type AgentdNativeProductLoadFuture<'a> = Pin<
    Box<dyn Future<Output = Result<AgentdCanonicalNativeCompositionV1, AgentdError>> + Send + 'a>,
>;

/// Startup loader implemented by the existing product embedding.
///
/// Implementations derive owners from their authoritative host sources for
/// this exact daemon identity. They must not admit a run, dispatch an effect,
/// create a grant issuer, or reconstruct seven owners from request JSON.
/// The recovered writer is supplied by the embedding's original verified
/// recovery path; this callback cannot replace the retained AgentdConfig.
///
/// No default/file-deserialization implementation is provided: the generic
/// Agentd binary does not contain a production implementation of the seven
/// intelligence owners' input provider. A grant socket alone is insufficient.
pub trait AgentdNativeProductLoaderV1: Send + Sync {
    fn load<'a>(&'a self, identity: &'a AgentdIdentity) -> AgentdNativeProductLoadFuture<'a>;
}

/// Load once, configure once, then enter the existing real daemon runtime.
///
/// Call this from the embedding's existing arg0-dispatch closure, after its
/// original `AgentdConfig`/process-home setup. Loader or configuration failure
/// is returned directly: this function never retries loading, falls back to
/// ordinary Core sampling, or starts a partial native runtime. The loader
/// object is dropped before the daemon runs; the returned owner handles own
/// their required lifetimes, without a second startup owner registry.
pub async fn run_native_product_with_loader(
    config: AgentdConfig,
    arg0_paths: Arg0DispatchPaths,
    loader: Box<dyn AgentdNativeProductLoaderV1>,
) -> Result<(), AgentdError> {
    let identity = config.identity().clone();
    let composition = loader.load(&identity).await?;
    let config = composition.configure(config)?;
    drop(loader);
    crate::run(config, arg0_paths).await
}
