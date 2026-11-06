//! The proposal schema binds complete model state to actual framed prefix bytes.

use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::decoder::Prefixes;
use crate::model::MODALITIES;
use crate::model::Model;
use crate::model::State;
use crate::protocol::EmissionLaw;
use crate::protocol::MAX_STATE_BYTES;
use crate::protocol::Sampler;

pub(crate) struct BridgeState {
    pub(crate) model: State,
    pub(crate) law: EmissionLaw,
    pub(crate) prefixes: Prefixes,
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
            prefixes: Prefixes::read(prefix)?,
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
        if Prefixes::read(prefix)? != self.prefixes {
            return Err("prefix projection mismatch".into());
        }
        let mut packet = self.model.packet();
        packet.meta.extend([
            ("kind".into(), "joint-generation-proposal-state-v1".into()),
            ("weights".into(), weights_hash.into()),
            ("input".into(), input_hash.into()),
            ("seed".into(), self.law.seed.to_string()),
            ("sampler".into(), self.law.sampler.name().into()),
            ("bridge.prefix_sha256".into(), sha256(prefix)),
        ]);
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
