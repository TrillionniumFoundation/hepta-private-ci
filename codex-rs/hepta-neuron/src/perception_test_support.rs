use crate::cell_test_support::checked;
use crate::*;

// Hand-authored interoperability data, not a trained encoder's measured output.
pub(crate) const PERCEPTION_FIXTURE: &[u8] =
    include_bytes!("../tests/fixtures/perception-bytes-v1.json");
pub(crate) const RAW: &[u8] = b"amount=19.99;not_paid;v=2.1";

pub(crate) fn observation() -> PerceptionObservationV1 {
    checked(PerceptionObservationV1::decode(PERCEPTION_FIXTURE))
}

pub(crate) fn actor_source() -> PerceptionActorSourceV1<'static> {
    checked(PerceptionActorSourceV1::new(
        observation().evidence[0].source.clone(),
        RAW,
    ))
}

pub(crate) fn binding(observation: &PerceptionObservationV1) -> PerceptionEncoderBindingV1 {
    PerceptionEncoderBindingV1 {
        encoder_digest: Digest32::from_array(observation.encoder_digest),
        latent_model_digest: Digest32::from_array(observation.latent_model_digest),
        residual_predictor_digest: None,
        representation: observation.representation,
        feature_dimension: observation
            .latents
            .iter()
            .map(|latent| latent.values_q24.len())
            .sum(),
    }
}
