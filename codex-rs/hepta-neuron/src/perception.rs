//! Bounded dual-channel observations. Latents are externally supplied outputs of
//! a pinned encoder, never hashes or fabricated evidence of model training.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;

use crate::perception_source::MAX_PERCEPTION_RAW_BYTES;
use crate::perception_source::PerceptionActorSourceV1;
use crate::perception_source::PerceptionErrorV1;
use crate::perception_source::PerceptionEvidenceV1;

const MAX_OBSERVATION_BYTES: usize = 65_536;
const MAX_EVIDENCE: usize = 64;
const MAX_FEATURES: usize = 4_096;
const Q24_LIMIT: i64 = 8 * (1 << 24);
const SCHEMA: &str = "hepta.perception.observation.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PerceptionRepresentationV1 {
    Global,
    Dense,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionLatentV1 {
    pub evidence_digests: Vec<[u8; 32]>,
    pub values_q24: Vec<i64>,
    /// None is unmeasured; it must not be silently replaced by zero.
    pub prediction_residual_q24: Option<i64>,
    pub residual_predictor_digest: Option<[u8; 32]>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PerceptionObservationV1 {
    pub schema: String,
    pub scope_digest: [u8; 32],
    pub source_frontier: [u8; 32],
    pub encoder_digest: [u8; 32],
    pub latent_model_digest: [u8; 32],
    pub representation: PerceptionRepresentationV1,
    pub evidence: Vec<PerceptionEvidenceV1>,
    pub latents: Vec<PerceptionLatentV1>,
}

/// Frozen adapter configuration. The encoder digest must also pin representation,
/// latent ordering, dimensions and preprocessing in the host's admitted bundle.
/// These pins do not prove that an encoder computed the supplied values; that
/// provenance remains with the host's admitted producer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PerceptionEncoderBindingV1 {
    pub encoder_digest: Digest32,
    pub latent_model_digest: Digest32,
    pub residual_predictor_digest: Option<Digest32>,
    pub representation: PerceptionRepresentationV1,
    pub feature_dimension: usize,
}

impl PerceptionEncoderBindingV1 {
    pub(crate) fn validate(&self) -> Result<(), PerceptionErrorV1> {
        if self.encoder_digest.is_zero()
            || self.latent_model_digest.is_zero()
            || self
                .residual_predictor_digest
                .is_some_and(Digest32::is_zero)
            || !(1..=MAX_FEATURES).contains(&self.feature_dimension)
        {
            return Err(PerceptionErrorV1::BindingMismatch);
        }
        Ok(())
    }
}

impl PerceptionObservationV1 {
    pub fn decode(bytes: &[u8]) -> Result<Self, PerceptionErrorV1> {
        if bytes.len() > MAX_OBSERVATION_BYTES {
            return Err(PerceptionErrorV1::Capacity);
        }
        let result: Self =
            serde_json::from_slice(bytes).map_err(|_| PerceptionErrorV1::InvalidWire)?;
        result.validate_structure()?;
        Ok(result)
    }

    pub fn encode(&self) -> Result<Vec<u8>, PerceptionErrorV1> {
        self.validate_structure()?;
        let bytes = serde_json::to_vec(self).map_err(|_| PerceptionErrorV1::InvalidWire)?;
        if bytes.len() > MAX_OBSERVATION_BYTES {
            return Err(PerceptionErrorV1::Capacity);
        }
        Ok(bytes)
    }

    /// Actor-source validation must precede use; decoding alone is not admission.
    pub fn validate(
        &self,
        binding: &PerceptionEncoderBindingV1,
        actor_sources: &[PerceptionActorSourceV1<'_>],
    ) -> Result<(), PerceptionErrorV1> {
        self.validate_structure()?;
        binding.validate()?;
        if self.encoder_digest != binding.encoder_digest.into_array()
            || self.latent_model_digest != binding.latent_model_digest.into_array()
            || self.representation != binding.representation
            || self
                .latents
                .iter()
                .map(|latent| latent.values_q24.len())
                .sum::<usize>()
                != binding.feature_dimension
            || self.latents.iter().any(|latent| {
                latent.residual_predictor_digest.is_some_and(|digest| {
                    Some(Digest32::from_array(digest)) != binding.residual_predictor_digest
                })
            })
        {
            return Err(PerceptionErrorV1::BindingMismatch);
        }
        if actor_sources.is_empty() || actor_sources.len() > MAX_EVIDENCE {
            return Err(PerceptionErrorV1::Capacity);
        }
        let mut sources = BTreeSet::new();
        for source in actor_sources {
            if !sources.insert(source.pin().source_id.as_str()) {
                return Err(PerceptionErrorV1::SourceMismatch);
            }
        }
        for evidence in &self.evidence {
            actor_sources
                .iter()
                .find(|source| source.pin().source_id == evidence.source.source_id)
                .ok_or(PerceptionErrorV1::SourceMismatch)?
                .matches(evidence)?;
        }
        Ok(())
    }

    /// Stable across global/dense ablations with the same admitted evidence.
    pub fn evidence_digest(&self) -> Result<Digest32, PerceptionErrorV1> {
        self.validate_structure()?;
        let mut bytes = b"hepta.perception.evidence-set.v1\0".to_vec();
        bytes.extend_from_slice(&self.source_frontier);
        for evidence in &self.evidence {
            bytes.extend_from_slice(evidence.digest()?.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate_structure(&self) -> Result<(), PerceptionErrorV1> {
        if self.schema != SCHEMA
            || [
                self.scope_digest,
                self.source_frontier,
                self.encoder_digest,
                self.latent_model_digest,
            ]
            .contains(&[0; 32])
        {
            return Err(PerceptionErrorV1::BindingMismatch);
        }
        if self.evidence.is_empty()
            || self.evidence.len() > MAX_EVIDENCE
            || self.latents.is_empty()
            || self.latents.len() > MAX_EVIDENCE
        {
            return Err(PerceptionErrorV1::Capacity);
        }
        let mut ids = BTreeSet::new();
        let mut digests = Vec::with_capacity(self.evidence.len());
        let mut raw_bytes = 0_usize;
        for evidence in &self.evidence {
            if !ids.insert(evidence.evidence_id.as_str()) {
                return Err(PerceptionErrorV1::InvalidEvidence);
            }
            raw_bytes = raw_bytes
                .checked_add(evidence.raw_bytes.len())
                .ok_or(PerceptionErrorV1::Capacity)?;
            if raw_bytes > MAX_PERCEPTION_RAW_BYTES {
                return Err(PerceptionErrorV1::Capacity);
            }
            digests.push(evidence.digest()?.into_array());
        }
        let coverage_matches = match self.representation {
            PerceptionRepresentationV1::Global => {
                self.latents.len() == 1 && self.latents[0].evidence_digests == digests
            }
            PerceptionRepresentationV1::Dense => {
                self.latents.len() == digests.len()
                    && self
                        .latents
                        .iter()
                        .zip(digests)
                        .all(|(latent, digest)| latent.evidence_digests == [digest])
            }
        };
        if !coverage_matches {
            return Err(PerceptionErrorV1::InvalidLatent);
        }
        let dimension = self.latents[0].values_q24.len();
        if dimension == 0
            || dimension
                .checked_mul(self.latents.len())
                .is_none_or(|size| size > MAX_FEATURES)
            || self.latents.iter().any(|latent| {
                latent.values_q24.len() != dimension
                    || latent
                        .values_q24
                        .iter()
                        .any(|value| !(-Q24_LIMIT..=Q24_LIMIT).contains(value))
                    || match (
                        latent.prediction_residual_q24,
                        latent.residual_predictor_digest,
                    ) {
                        (None, None) => false,
                        (Some(value), Some(digest)) => {
                            !(0..=Q24_LIMIT).contains(&value) || digest == [0; 32]
                        }
                        (None, Some(_)) | (Some(_), None) => true,
                    }
            })
        {
            return Err(PerceptionErrorV1::InvalidLatent);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "perception_tests.rs"]
mod tests;
