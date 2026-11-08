//! Version four observation and ordered byte encoder, separate from v3 numerics.

use crate::codec::Packet;
use crate::codec::Result;
use crate::math::cat;
use crate::math::linear;
use crate::math::tanh;
use crate::model::Model;
use crate::model::State;
use crate::observation::DeliveryObservation;

impl Model {
    pub(crate) fn is_observed(&self) -> bool {
        self.observed
    }

    pub(crate) fn total_units(&self) -> [u32; 4] {
        [
            16,
            1024,
            4,
            if self.observed {
                crate::text_codec::TEXT_SCALAR_LIMIT
            } else {
                2
            },
        ]
    }

    pub(crate) fn ordered_text(&self, tokens: &[f64]) -> Result<Vec<f64>> {
        let table = self.weights.get("token_encoder.weight")?;
        let mut hidden = vec![0.0; self.width];
        for token in tokens {
            let mut next = linear(&self.weights, "text_recurrent", &hidden)?;
            let index = *token as usize;
            for (channel, value) in next.iter_mut().enumerate() {
                *value += table[index * self.width + channel];
            }
            hidden = tanh(next);
        }
        Ok(hidden)
    }

    pub(crate) fn features_observed(
        &self,
        state: &State,
        observation: &DeliveryObservation,
    ) -> Result<Vec<f64>> {
        observation.owner.validate()?;
        if !self.observed
            || observation.totals != self.total_units()
            || observation
                .cursors
                .iter()
                .zip(observation.totals)
                .any(|(cursor, total)| *cursor > total)
        {
            return Err("observation/model profile mismatch".into());
        }
        let mut features = self.features(state, observation.remaining_fraction());
        features.extend(observation.features());
        Ok(features)
    }

    pub(crate) fn inspect_observed(
        &self,
        state: &State,
        observation: &DeliveryObservation,
    ) -> Result<Packet> {
        let features = self.features_observed(state, observation)?;
        let mut result = self.inspect_features(state, &features, Some(observation))?;
        result.vector("observation.features", observation.features());
        result.vector(
            "observation.cursors",
            observation.cursors.map(f64::from).to_vec(),
        );
        result.meta.insert(
            "observation.profile".into(),
            crate::observation::OBSERVATION_PROFILE.into(),
        );
        result.meta.insert(
            "observation.budget_total".into(),
            observation.owner.budget_total.to_string(),
        );
        result.meta.insert(
            "observation.budget_remaining".into(),
            observation.owner.budget_remaining.to_string(),
        );
        Ok(result)
    }

    pub(crate) fn byte_logits(&self, state: &State) -> Result<Vec<f64>> {
        let text = state.text.as_ref().ok_or("missing byte decoder state")?;
        linear(
            &self.weights,
            "emissions.text",
            &cat(&[&state.shared, &text.hidden]),
        )
    }

    pub(crate) fn consume_byte(&self, state: &mut State, byte: u8) -> Result<()> {
        let text = state.text.as_ref().ok_or("missing byte decoder state")?;
        let mut next = linear(&self.weights, "text_recurrent", &text.hidden)?;
        let condition = linear(
            &self.weights,
            "text_condition",
            &cat(&[&state.shared, &state.slots[3 * self.width..4 * self.width]]),
        )?;
        let table = self.weights.get("token_encoder.weight")?;
        for (channel, value) in next.iter_mut().enumerate() {
            *value += condition[channel] + table[usize::from(byte) * self.width + channel];
        }
        let text = state.text.as_mut().ok_or("missing byte decoder state")?;
        text.hidden = tanh(next);
        text.bytes = text
            .bytes
            .checked_add(1)
            .ok_or("text byte cursor overflow")?;
        Ok(())
    }
}
