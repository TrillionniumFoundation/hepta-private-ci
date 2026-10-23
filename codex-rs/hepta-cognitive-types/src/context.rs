//! Contextual validation borrows the exact immutable context used by a check.
//!
//! Raw DTO -> `Validated<T>` -> a contextual view are distinct stages. Neither
//! a caller-supplied asset manifest nor its digest authenticates an owner.
//! The existing owner must authenticate the context and revalidate at final use.

use crate::contract::Validated;
use crate::hnmf::AssetManifestV1;
use crate::hnmf::CrossModalBindingV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::MemoryEventV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf::validate_cross_modal_binding_against_event_v1;
use crate::hnmf::validate_span_against_manifest_v1;

/// Borrows the checked span and its manifest, preventing safe mutation of
/// either value while this contextual proof is in use. It conveys no authority.
#[derive(Debug)]
pub struct ManifestCheckedSpanV1<'a> {
    span: &'a Validated<ModalitySpanRefV1>,
    manifest: &'a AssetManifestV1,
}

impl<'a> ManifestCheckedSpanV1<'a> {
    pub fn new(
        span: &'a Validated<ModalitySpanRefV1>,
        manifest: &'a AssetManifestV1,
    ) -> Result<Self, HnmfContractError> {
        validate_span_against_manifest_v1(manifest, span.as_inner())?;
        Ok(Self { span, manifest })
    }

    #[must_use]
    pub const fn span(&self) -> &Validated<ModalitySpanRefV1> {
        self.span
    }

    #[must_use]
    pub const fn manifest(&self) -> &AssetManifestV1 {
        self.manifest
    }
}

#[derive(Debug)]
pub struct EventCheckedBindingV1<'a> {
    binding: &'a Validated<CrossModalBindingV1>,
    event: &'a Validated<MemoryEventV1>,
}

impl<'a> EventCheckedBindingV1<'a> {
    pub fn new(
        binding: &'a Validated<CrossModalBindingV1>,
        event: &'a Validated<MemoryEventV1>,
    ) -> Result<Self, HnmfContractError> {
        validate_cross_modal_binding_against_event_v1(event.as_inner(), binding.as_inner())?;
        Ok(Self { binding, event })
    }

    #[must_use]
    pub const fn binding(&self) -> &Validated<CrossModalBindingV1> {
        self.binding
    }

    #[must_use]
    pub const fn event(&self) -> &Validated<MemoryEventV1> {
        self.event
    }
}
