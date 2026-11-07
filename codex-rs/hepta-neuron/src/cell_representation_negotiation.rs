//! Explicit producer/consumer agreement. Exact equality permits direct use;
//! every conversion requires a separately approved, fully pinned component.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellScopeV1;
use crate::cell_representation::CellRepresentationV1;
use crate::cell_representation_profile::CellRepresentationErrorV1;
use crate::cell_representation_profile::CellRepresentationProfileV1;
use crate::cell_representation_profile::MAX_REPRESENTATION_BYTES;
use crate::cell_representation_profile::compact_id;
use crate::cell_representation_profile::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationProducerV1 {
    pub producer_id: StableId,
    pub generation: Generation,
    pub binding_digest: Digest32,
    pub offered_profiles: Vec<Digest32>,
    pub max_payload_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationConsumerV1 {
    pub consumer_id: StableId,
    pub generation: Generation,
    /// The exact current backend/owner contract, not just its display name.
    pub binding_digest: Digest32,
    pub accepted_profiles: Vec<Digest32>,
    /// Pins resolved by the existing artifacts/evaluation owner after quality
    /// review. A component's self-supplied evidence hash cannot approve itself.
    pub qualified_projections: Vec<Digest32>,
    pub max_payload_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellProjectionComponentV1 {
    pub component_id: StableId,
    pub generation: Generation,
    pub input_profile_digest: Digest32,
    pub output_profile_digest: Digest32,
    pub implementation_digest: Digest32,
    pub parameters_digest: Digest32,
    pub quality_evidence_digest: Digest32,
}

impl CellProjectionComponentV1 {
    /// This statement binds quality evidence; authenticating its provenance and
    /// deciding that it qualifies the intended task remain with their owners.
    pub fn digest(&self) -> Result<Digest32, CellRepresentationErrorV1> {
        let mut bytes = b"hepta.cell.representation-projection.v1\0".to_vec();
        push_id(&mut bytes, &self.component_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in [
            self.input_profile_digest,
            self.output_profile_digest,
            self.implementation_digest,
            self.parameters_digest,
            self.quality_evidence_digest,
        ] {
            if digest.is_zero() {
                return Err(CellRepresentationErrorV1::UnqualifiedProjection);
            }
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Endpoint pins read from its current owner at use time. `contract_digest`
/// covers the complete producer/consumer advertisement, including its profile,
/// projection and budget policy. Copying pins from an old negotiation is not a
/// current observation and provides neither authentication nor authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationEndpointUseV1 {
    pub endpoint_id: StableId,
    pub generation: Generation,
    pub binding_digest: Digest32,
    pub contract_digest: Digest32,
}

/// Fresh owner observations supplied at the actual consumer. The host resolves
/// and authenticates both endpoints independently of the source and negotiation;
/// these equality checks grant neither source access nor an external effect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationUseV1 {
    pub producer: CellRepresentationEndpointUseV1,
    pub consumer: CellRepresentationEndpointUseV1,
    pub scope: CellScopeV1,
    pub source_frontier: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationNegotiationV1 {
    pub(crate) producer: CellRepresentationProducerV1,
    pub(crate) consumer: CellRepresentationConsumerV1,
    pub(crate) input_profile: CellRepresentationProfileV1,
    pub(crate) output_profile: CellRepresentationProfileV1,
    pub(crate) projection: Option<CellProjectionComponentV1>,
    input_profile_digest: Digest32,
    digest: Digest32,
}

impl CellRepresentationNegotiationV1 {
    pub fn direct(
        producer: CellRepresentationProducerV1,
        consumer: CellRepresentationConsumerV1,
        profile: CellRepresentationProfileV1,
    ) -> Result<Self, CellRepresentationErrorV1> {
        let profile = profile.into_compact()?;
        Self::negotiate(producer, consumer, profile.clone(), profile, /*projection*/ None)
    }

    pub fn projected(
        producer: CellRepresentationProducerV1,
        consumer: CellRepresentationConsumerV1,
        input_profile: CellRepresentationProfileV1,
        output_profile: CellRepresentationProfileV1,
        projection: CellProjectionComponentV1,
    ) -> Result<Self, CellRepresentationErrorV1> {
        Self::negotiate(producer, consumer, input_profile, output_profile, Some(projection))
    }

    fn negotiate(
        mut producer: CellRepresentationProducerV1,
        mut consumer: CellRepresentationConsumerV1,
        input_profile: CellRepresentationProfileV1,
        output_profile: CellRepresentationProfileV1,
        mut projection: Option<CellProjectionComponentV1>,
    ) -> Result<Self, CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        let input_profile_digest = input_profile.digest()?;
        let output_profile_digest = output_profile.digest()?;
        let mut bytes = b"hepta.cell.representation-negotiation.v1\0".to_vec();
        bytes.extend_from_slice(producer.digest()?.as_array());
        bytes.extend_from_slice(consumer.digest()?.as_array());
        if !producer.offered_profiles.contains(&input_profile_digest)
            || !consumer.accepted_profiles.contains(&output_profile_digest)
        {
            return Err(E::Incompatible);
        }
        for digest in [input_profile_digest, output_profile_digest] {
            bytes.extend_from_slice(digest.as_array());
        }
        match &projection {
            Some(component) => {
                let digest = component.digest()?;
                if component.input_profile_digest != input_profile_digest
                    || component.output_profile_digest != output_profile_digest
                {
                    return Err(E::Incompatible);
                }
                if !consumer.qualified_projections.contains(&digest) {
                    return Err(E::UnqualifiedProjection);
                }
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => {
                if input_profile_digest != output_profile_digest {
                    return Err(E::Incompatible);
                }
                bytes.push(0);
            }
        }
        producer.producer_id = compact_id(&producer.producer_id)?;
        producer.offered_profiles = producer.offered_profiles.into_boxed_slice().into_vec();
        consumer.consumer_id = compact_id(&consumer.consumer_id)?;
        consumer.accepted_profiles = consumer.accepted_profiles.into_boxed_slice().into_vec();
        consumer.qualified_projections = consumer.qualified_projections.into_boxed_slice().into_vec();
        if let Some(component) = &mut projection {
            component.component_id = compact_id(&component.component_id)?;
        }
        Ok(Self {
            producer,
            consumer,
            input_profile: input_profile.into_compact()?,
            output_profile: output_profile.into_compact()?,
            projection,
            input_profile_digest,
            digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    /// Borrow the full, exactly negotiated representation. A projected route
    /// cannot use this to hand untranslated source bytes to the consumer.
    pub fn consume_direct<'a>(
        &self,
        source: &'a CellRepresentationV1,
        current: &CellRepresentationUseV1,
    ) -> Result<&'a CellRepresentationV1, CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        self.validate_use(source, current)?;
        if self.projection.is_some() {
            return Err(E::ProjectionRequired);
        }
        if source.payload_bytes() > self.consumer.max_payload_bytes {
            return Err(E::Capacity);
        }
        Ok(source)
    }

    /// Recheck both owner observations when the representation is consumed or
    /// projected. A successful negotiation does not freeze either owner forever.
    pub fn validate_use(
        &self,
        source: &CellRepresentationV1,
        current: &CellRepresentationUseV1,
    ) -> Result<(), CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        self.check_source(source)?;
        if current.producer.endpoint_id != self.producer.producer_id
            || current.producer.generation != self.producer.generation
            || current.producer.binding_digest != self.producer.binding_digest
            || current.producer.contract_digest != self.producer.digest()?
        {
            return Err(E::StaleProducer);
        }
        if current.consumer.endpoint_id != self.consumer.consumer_id
            || current.consumer.generation != self.consumer.generation
            || current.consumer.binding_digest != self.consumer.binding_digest
            || current.consumer.contract_digest != self.consumer.digest()?
        {
            return Err(E::StaleConsumer);
        }
        if current.scope != source.context().scope {
            return Err(E::ScopeMismatch);
        }
        if current.source_frontier != source.context().source_frontier {
            return Err(E::StaleSource);
        }
        Ok(())
    }

    pub(crate) fn check_source(
        &self,
        source: &CellRepresentationV1,
    ) -> Result<(), CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        if source.profile_digest() != self.input_profile_digest {
            return Err(E::Incompatible);
        }
        let context = source.context();
        if context.producer_id != self.producer.producer_id
            || context.producer_generation != self.producer.generation
            || context.producer_binding_digest != self.producer.binding_digest
        {
            return Err(E::StaleProducer);
        }
        if source.payload_bytes() > self.producer.max_payload_bytes {
            return Err(E::Capacity);
        }
        Ok(())
    }
}

impl CellRepresentationProducerV1 {
    pub fn digest(&self) -> Result<Digest32, CellRepresentationErrorV1> {
        endpoint_digest(
            b"hepta.cell.representation-producer.v1\0",
            &self.producer_id,
            self.generation,
            self.binding_digest,
            &self.offered_profiles,
            /*projections*/ &[],
            self.max_payload_bytes,
        )
    }
}

impl CellRepresentationConsumerV1 {
    pub fn digest(&self) -> Result<Digest32, CellRepresentationErrorV1> {
        endpoint_digest(
            b"hepta.cell.representation-consumer.v1\0",
            &self.consumer_id,
            self.generation,
            self.binding_digest,
            &self.accepted_profiles,
            &self.qualified_projections,
            self.max_payload_bytes,
        )
    }
}

fn endpoint_digest(
    prefix: &[u8],
    id: &StableId,
    generation: Generation,
    binding: Digest32,
    profiles: &[Digest32],
    projections: &[Digest32],
    max_payload_bytes: u64,
) -> Result<Digest32, CellRepresentationErrorV1> {
    use CellRepresentationErrorV1 as E;

    if binding.is_zero() || profiles.is_empty() || profiles.len() > 16 || projections.len() > 32 {
        return Err(E::InvalidProfile);
    }
    if !(1..=MAX_REPRESENTATION_BYTES).contains(&max_payload_bytes) {
        return Err(E::Capacity);
    }
    let mut bytes = prefix.to_vec();
    push_id(&mut bytes, id);
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&max_payload_bytes.to_be_bytes());
    for digests in [profiles, projections] {
        if digests.iter().copied().any(Digest32::is_zero)
            || digests.iter().collect::<BTreeSet<_>>().len() != digests.len()
        {
            return Err(E::InvalidProfile);
        }
        bytes.extend_from_slice(&(digests.len() as u64).to_be_bytes());
        for digest in digests {
            bytes.extend_from_slice(digest.as_array());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}
