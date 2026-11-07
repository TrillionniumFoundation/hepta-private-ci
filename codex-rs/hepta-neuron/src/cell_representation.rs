//! Bounded, immutable representation bytes and their common causal envelope.
//! The source owner supplies current pins. Content hashes do not authenticate
//! that owner, grant tensor custody or imply approval to update model state.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellScopeV1;
use crate::cell_representation_profile::CellRepresentationErrorV1;
use crate::cell_representation_profile::CellRepresentationProfileV1;
use crate::cell_representation_profile::CellTensorRoleV1;
use crate::cell_representation_profile::compact_id;
use crate::cell_representation_profile::push_id;

/// Producer/artifact and source identities are independent of the consumer's
/// state generation. The caller resolves and rechecks their current owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationContextV1 {
    pub producer_id: StableId,
    pub producer_generation: Generation,
    pub producer_binding_digest: Digest32,
    pub scope: CellScopeV1,
    pub source_frontier: Digest32,
    pub source_bundle_digest: Digest32,
    pub source_record_digest: Digest32,
    pub causal_receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellTensorValueV1 {
    Present(Vec<u8>),
    /// Explicit absence with a versioned reason, never a fabricated zero tensor.
    Missing {
        reason: StableId,
    },
}

/// Tensor order exactly matches the profile. No decoder may guess names or
/// shapes from byte lengths. Returned borrows cannot mutate the sealed values.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationV1 {
    profile: CellRepresentationProfileV1,
    profile_digest: Digest32,
    context: CellRepresentationContextV1,
    values: Vec<CellTensorValueV1>,
    payload_bytes: u64,
    manifest: Vec<u8>,
    digest: Digest32,
}

impl CellRepresentationV1 {
    pub fn new(
        profile: CellRepresentationProfileV1,
        mut context: CellRepresentationContextV1,
        mut values: Vec<CellTensorValueV1>,
    ) -> Result<Self, CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        let profile = profile.into_compact()?;
        let profile_digest = profile.digest()?;
        if context.scope.principal_digest.is_zero()
            || [
                context.producer_binding_digest,
                context.source_frontier,
                context.source_bundle_digest,
                context.source_record_digest,
                context.causal_receipt_digest,
            ]
            .into_iter()
            .any(Digest32::is_zero)
        {
            return Err(E::InvalidPayload);
        }
        if values.len() != profile.tensors.len() {
            return Err(E::InvalidPayload);
        }
        let mut payload_bytes = 0_u64;
        let mut modalities = BTreeMap::new();
        // Check dimensions and all byte bounds before hashing supplied data.
        for (layout, value) in profile.tensors.iter().zip(&values) {
            let absence = match value {
                CellTensorValueV1::Present(bytes) => {
                    if bytes.len() as u64 != layout.byte_len()?
                        || (layout.role == CellTensorRoleV1::Mask
                            && bytes.iter().any(|value| *value > 1))
                    {
                        return Err(E::InvalidPayload);
                    }
                    payload_bytes = payload_bytes
                        .checked_add(bytes.len() as u64)
                        .ok_or(E::Capacity)?;
                    None
                }
                CellTensorValueV1::Missing { reason } => {
                    if !layout.optional {
                        return Err(E::InvalidPayload);
                    }
                    Some(reason)
                }
            };
            if let Some(modality) = &layout.modality
                && let Some(previous) = modalities.insert(modality, absence)
                && previous != absence
            {
                return Err(E::InvalidPayload);
            }
        }
        if payload_bytes > profile.max_payload_bytes {
            return Err(E::Capacity);
        }
        drop(modalities);
        context.producer_id = compact_id(&context.producer_id)?;
        context.scope.agent_id = compact_id(&context.scope.agent_id)?;
        context.scope.cell_id = compact_id(&context.scope.cell_id)?;
        context.scope.run_id = compact_id(&context.scope.run_id)?;
        // Preserve exact data, while releasing caller-supplied spare capacity.
        // The payload limit does not purport to measure allocator or process RSS.
        for value in &mut values {
            match value {
                CellTensorValueV1::Present(bytes) => {
                    *bytes = std::mem::take(bytes).into_boxed_slice().into_vec();
                }
                CellTensorValueV1::Missing { reason } => *reason = compact_id(reason)?,
            }
        }
        let values = values.into_boxed_slice().into_vec();
        let mut manifest = b"hepta.cell.representation-envelope.v1\0".to_vec();
        push_id(&mut manifest, &context.producer_id);
        manifest.extend_from_slice(&context.producer_generation.get().to_be_bytes());
        for digest in [
            profile_digest,
            context.producer_binding_digest,
            context.scope.digest(),
            context.source_frontier,
            context.source_bundle_digest,
            context.source_record_digest,
            context.causal_receipt_digest,
        ] {
            manifest.extend_from_slice(digest.as_array());
        }
        manifest.extend_from_slice(&payload_bytes.to_be_bytes());
        manifest.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in &values {
            match value {
                CellTensorValueV1::Present(bytes) => {
                    manifest.push(0);
                    manifest.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
                    manifest.extend_from_slice(Digest32::of_bytes(bytes).as_array());
                }
                CellTensorValueV1::Missing { reason } => {
                    manifest.push(1);
                    push_id(&mut manifest, reason);
                }
            }
        }
        let digest = Digest32::of_bytes(&manifest);
        Ok(Self {
            profile,
            profile_digest,
            context,
            values,
            payload_bytes,
            manifest,
            digest,
        })
    }

    pub fn profile(&self) -> &CellRepresentationProfileV1 {
        &self.profile
    }

    pub fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    pub fn context(&self) -> &CellRepresentationContextV1 {
        &self.context
    }

    pub fn tensors(&self) -> &[CellTensorValueV1] {
        &self.values
    }

    pub fn payload_bytes(&self) -> u64 {
        self.payload_bytes
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub(crate) fn manifest(&self) -> &[u8] {
        &self.manifest
    }
}

#[cfg(test)]
#[path = "cell_representation_tests.rs"]
mod tests;
