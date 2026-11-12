//! Immutable assets and deterministic initial encoding shared by one resident.
//! Each request receives its own state clone before any transition.

use std::sync::OnceLock;

use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::model::Model;
use crate::planner;
use crate::state::State;

pub(crate) struct LoadedModel {
    pub(crate) model: Model,
    pub(crate) public: Packet,
    pub(crate) weights_hash: String,
    pub(crate) input_hash: String,
    initial: OnceLock<Result<State>>,
}

impl LoadedModel {
    pub(crate) fn load(weights: &[u8], public: &[u8]) -> Result<Self> {
        let model = Model::new(canonical_packet(weights)?)?;
        if model.width != 32
            || model.depth != 1
            || model.mode != "dual"
            || model.boundary != "direct"
        {
            return Err("bridge requires selected width32/depth1/dual/direct profile".into());
        }
        if model.is_observed() {
            planner::validate_profile(&model)?;
        }
        let public_packet = canonical_packet(public)?;
        model.validate_input(&public_packet)?;
        Ok(Self {
            model,
            public: public_packet,
            weights_hash: sha256(weights),
            input_hash: sha256(public),
            initial: OnceLock::new(),
        })
    }

    pub(crate) fn initial_state(&self) -> Result<State> {
        self.initial
            .get_or_init(|| self.model.encode(&self.public))
            .clone()
    }
}

fn canonical_packet(bytes: &[u8]) -> Result<Packet> {
    let packet = Packet::decode(bytes)?;
    if packet.encode()? != bytes {
        return Err("noncanonical asset packet".into());
    }
    Ok(packet)
}
