//! The proposal schema binds complete model state to actual framed prefix bytes.

use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::decoder::Prefixes;
use crate::model::MODALITIES;
use crate::model::Model;
use crate::model::State;
use crate::observation::DeliveryObservation;
use crate::observation::OwnerContext;
use crate::protocol::EmissionLaw;
use crate::protocol::MAX_STATE_BYTES;
use crate::protocol::Sampler;

pub(crate) struct BridgeState {
    pub(crate) model: State,
    pub(crate) law: EmissionLaw,
    pub(crate) prefixes: Prefixes,
    pub(crate) owner: Option<OwnerContext>,
    pub(crate) planning: Option<crate::planner::PlanningReceipt>,
}

impl BridgeState {
    pub(crate) fn read(
        bytes: &[u8],
        model: &Model,
        weights_hash: &str,
        input_hash: &str,
        prefix: &[u8],
    ) -> Result<Self> {
        let packet = Packet::decode(bytes)?;
        let state = Self {
            model: State::read(&packet, model)?,
            law: EmissionLaw {
                seed: packet.text("seed")?.parse().map_err(|_| "invalid seed")?,
                sampler: Sampler::parse(packet.text("sampler")?)?,
            },
            prefixes: Prefixes::read_for_model(prefix, model)?,
            owner: if model.is_observed() {
                Some(OwnerContext::read_packet(&packet)?)
            } else {
                None
            },
            planning: crate::planner::PlanningReceipt::read(&packet)?,
        };
        // Rebuild the entire inventory and compare canonical bytes, rather than
        // trusting self-asserted prefix hashes, cursor fields or extra tensors.
        if state.encode(weights_hash, input_hash, prefix)? != bytes {
            return Err("state/prefix/asset binding or canonical inventory mismatch".into());
        }
        Ok(state)
    }

    pub(crate) fn encode(
        &self,
        weights_hash: &str,
        input_hash: &str,
        prefix: &[u8],
    ) -> Result<Vec<u8>> {
        if Prefixes::read_profile(prefix, self.prefixes.observed)? != self.prefixes {
            return Err("prefix projection mismatch".into());
        }
        if self.prefixes.observed != self.owner.is_some()
            || self.prefixes.observed != self.model.text.is_some()
        {
            return Err("inconsistent bridge observation profile".into());
        }
        if self.owner.is_none() && self.planning.is_some() {
            return Err("legacy state cannot contain a v4 planning receipt".into());
        }
        if let Some(owner) = &self.owner {
            let totals = [16, 1024, 4, crate::text_codec::TEXT_SCALAR_LIMIT];
            let observation = DeliveryObservation::new(owner, &self.prefixes, totals)?;
            if self.model.stopped && !observation.required_complete() {
                return Err("stopped state has incomplete required delivery".into());
            }
            let text = self
                .model
                .text
                .as_ref()
                .ok_or("missing byte decoder state")?;
            if text.units != self.prefixes.cursors[3]
                || text.bytes as usize != self.prefixes.bytes[3].len()
            {
                return Err("text decoder/prefix cursor mismatch".into());
            }
        }
        let mut packet = self.model.packet();
        packet.meta.extend([
            (
                "kind".into(),
                if self.owner.is_some() {
                    "joint-generation-proposal-state-v2"
                } else {
                    "joint-generation-proposal-state-v1"
                }
                .into(),
            ),
            ("weights".into(), weights_hash.into()),
            ("input".into(), input_hash.into()),
            ("seed".into(), self.law.seed.to_string()),
            ("sampler".into(), self.law.sampler.name().into()),
            ("bridge.prefix_sha256".into(), sha256(prefix)),
        ]);
        if let Some(owner) = &self.owner {
            owner.write_packet(&mut packet);
        }
        if let Some(planning) = &self.planning {
            planning.write_packet(&mut packet);
        }
        for (index, modality) in MODALITIES.iter().enumerate() {
            packet.meta.insert(
                format!("cursor.{modality}"),
                self.prefixes.cursors[index].to_string(),
            );
            packet.vector(
                &format!("prefix.{modality}"),
                self.prefixes.bytes[index]
                    .iter()
                    .map(|byte| f64::from(*byte))
                    .collect(),
            );
        }
        let bytes = packet.encode()?;
        if bytes.len() > MAX_STATE_BYTES {
            return Err("state exceeds bridge bound".into());
        }
        Ok(bytes)
    }
}
