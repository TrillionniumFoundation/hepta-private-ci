//! Product prompt-runtime extension with an explicit legacy/V2 cutover.

#![forbid(unsafe_code)]

use std::fmt;

use codex_extension_api::ExtensionRegistryBuilder;

#[path = "lib.rs"]
mod legacy;
mod context_runtime_v2;

pub use context_runtime_v2::ContextCompilerRuntimeAttachmentMetadataV2;
pub use context_runtime_v2::ContextCompilerRuntimeAttachmentV2;
pub use context_runtime_v2::ContextCompilerRuntimeDispatchFutureV2;
pub use context_runtime_v2::ContextCompilerRuntimeDispatchV2;
pub use context_runtime_v2::ContextCompilerRuntimeFinalUseFutureV2;
pub use context_runtime_v2::ContextCompilerRuntimeFinalUseV2;
pub use context_runtime_v2::ContextCompilerRuntimeHostErrorV2;
pub use context_runtime_v2::ContextCompilerRuntimeHostV2;
pub use context_runtime_v2::ContextCompilerRuntimePrepareFutureV2;
pub use context_runtime_v2::ContextCompilerRuntimePrepareRequestV2;
pub use context_runtime_v2::ContextCompilerRuntimeRecordFutureV2;
pub use context_runtime_v2::ContextCompilerRuntimeTerminalV2;
pub use legacy::PromptRuntimeAttachmentV1;
pub use legacy::PromptRuntimeDeveloperFragmentV1;
pub use legacy::PromptRuntimeDispatchFuture;
pub use legacy::PromptRuntimeDispatchRecordV1;
pub use legacy::PromptRuntimeError;
pub use legacy::PromptRuntimeHostError;
pub use legacy::PromptRuntimePrepareFuture;
pub use legacy::PromptRuntimePrepareRequest;
pub use legacy::PromptRuntimeRecordFuture;
pub use legacy::PromptRuntimeTerminalOutcomeV1;
pub use legacy::PromptRuntimeTerminalRecordV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptRuntimeMode {
    LegacyV1,
    ContextCompilerV2,
}

#[derive(Clone)]
enum PromptRuntimeHostInner {
    Legacy(legacy::PromptRuntimeHost),
    ContextCompilerV2(ContextCompilerRuntimeHostV2),
}

/// Exactly one prompt runtime mode may be installed in an App Server process.
///
/// `new` preserves the existing legacy constructor. Canonical context.compiler
/// product code must use `new_context_compiler_v2`; the two paths are never
/// registered together.
#[derive(Clone)]
pub struct PromptRuntimeHost {
    inner: PromptRuntimeHostInner,
}

impl PromptRuntimeHost {
    pub fn new<P, D, R>(
        capability_id: impl Into<String>,
        prepare: P,
        dispatch: D,
        record: R,
    ) -> Result<Self, PromptRuntimeError>
    where
        P: Fn(PromptRuntimePrepareRequest) -> PromptRuntimePrepareFuture + Send + Sync + 'static,
        D: Fn(PromptRuntimeDispatchRecordV1) -> PromptRuntimeDispatchFuture + Send + Sync + 'static,
        R: Fn(PromptRuntimeTerminalRecordV1) -> PromptRuntimeRecordFuture + Send + Sync + 'static,
    {
        legacy::PromptRuntimeHost::new(capability_id, prepare, dispatch, record)
            .map(|host| Self {
                inner: PromptRuntimeHostInner::Legacy(host),
            })
    }

    #[must_use]
    pub fn new_context_compiler_v2(host: ContextCompilerRuntimeHostV2) -> Self {
        Self {
            inner: PromptRuntimeHostInner::ContextCompilerV2(host),
        }
    }

    #[must_use]
    pub const fn mode(&self) -> PromptRuntimeMode {
        match &self.inner {
            PromptRuntimeHostInner::Legacy(_) => PromptRuntimeMode::LegacyV1,
            PromptRuntimeHostInner::ContextCompilerV2(_) => PromptRuntimeMode::ContextCompilerV2,
        }
    }
}

impl fmt::Debug for PromptRuntimeHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRuntimeHost")
            .field("mode", &self.mode())
            .finish_non_exhaustive()
    }
}

impl PartialEq for PromptRuntimeHost {
    fn eq(&self, other: &Self) -> bool {
        match (&self.inner, &other.inner) {
            (PromptRuntimeHostInner::Legacy(left), PromptRuntimeHostInner::Legacy(right)) => {
                left == right
            }
            (
                PromptRuntimeHostInner::ContextCompilerV2(left),
                PromptRuntimeHostInner::ContextCompilerV2(right),
            ) => left == right,
            _ => false,
        }
    }
}

impl Eq for PromptRuntimeHost {}

pub fn install_prompt_runtime<C: Sync>(
    builder: &mut ExtensionRegistryBuilder<C>,
    host: PromptRuntimeHost,
) {
    match host.inner {
        PromptRuntimeHostInner::Legacy(host) => legacy::install_prompt_runtime(builder, host),
        PromptRuntimeHostInner::ContextCompilerV2(host) => {
            context_runtime_v2::install_context_compiler_runtime_v2(builder, host);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::ContextCompilerRuntimeHostV2;
    use super::PromptRuntimeMode;
    use super::PromptRuntimeHost;

    #[test]
    fn runtime_modes_are_mutually_exclusive() {
        let host = ContextCompilerRuntimeHostV2::new(
            "context.compiler.runtime.v2",
            |_request| Box::pin(std::future::ready(Ok(None))),
            |_request| Box::pin(std::future::ready(Ok(()))),
            |_record| Box::pin(std::future::ready(Ok(()))),
            |_record| Box::pin(std::future::ready(Ok(()))),
        )
        .unwrap_or_else(|error| panic!("host: {error}"));
        let wrapper = PromptRuntimeHost::new_context_compiler_v2(host);
        assert_eq!(wrapper.mode(), PromptRuntimeMode::ContextCompilerV2);
    }
}
