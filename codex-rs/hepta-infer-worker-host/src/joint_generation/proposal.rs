//! Execute the selected real numeric kernel without any persistent owner.

use std::io::Read;
use std::io::Write;
use std::sync::OnceLock;
use std::time::Instant;

use crate::bridge_state::BridgeState;
use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::decoder::Prefixes;
use crate::decoder::TOTAL_UNITS;
use crate::decoder::chunk;
use crate::model::ACTIONS;
use crate::model::Model;
use crate::protocol::Command;
use crate::protocol::MAX_DELTA_BYTES;
use crate::protocol::MAX_PREFIX_BYTES;
use crate::protocol::MAX_REQUEST_BYTES;
use crate::protocol::Request;
use crate::protocol::Response;
use crate::protocol::parse;

pub(crate) fn run_stdio() -> Result<()> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .lock()
        .take(MAX_REQUEST_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    let response = propose(&bytes)?.encode()?;
    let mut output = std::io::stdout().lock();
    output
        .write_all(&response)
        .and_then(|()| output.flush())
        .map_err(|error| error.to_string())
}

/// Immutable numerical assets shared by every request in a resident process.
/// Cell state, decoder cursors and output are always supplied by each request.
pub(crate) struct LoadedModel {
    model: Model,
    public: Packet,
    weights_hash: String,
    input_hash: String,
    initial: OnceLock<Result<crate::state::State>>,
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
        let input = canonical_packet(public)?;
        model.validate_input(&input)?;
        Ok(Self {
            model,
            public: input,
            weights_hash: sha256(weights),
            input_hash: sha256(public),
            initial: OnceLock::new(),
        })
    }

    pub(crate) fn propose(&self, request: Request<'_>, codec_start: Instant) -> Result<Response> {
        let Self {
            model,
            public,
            weights_hash,
            input_hash,
            initial,
        } = self;
        let prior = match request.command {
            Command::Init(_) => {
                if !request.state.is_empty() || !request.prefix.is_empty() {
                    return Err("init requires empty state and prefix".into());
                }
                None
            }
            _ => Some(BridgeState::read(
                request.state,
                model,
                weights_hash,
                input_hash,
                request.prefix,
            )?),
        };
        let mut phases = [elapsed(codec_start)?, 0, 0, 0];
        let mut state = if let Some(prior) = prior {
            if prior.model.stopped {
                return Err("stopped state cannot continue".into());
            }
            prior
        } else {
            let Command::Init(law) = request.command else {
                return Err("missing predecessor".into());
            };
            let start = Instant::now();
            // This public-input encoding is immutable. Each Cell receives a clone;
            // later transitions never write into the cached initial tensors.
            let encoded = initial
                .get_or_init(|| model.encode(public))
                .as_ref()
                .map_err(Clone::clone)?
                .clone();
            phases[1] = elapsed(start)?;
            BridgeState {
                model: encoded,
                law,
                prefixes: Prefixes::default(),
            }
        };
        let action = match request.command {
            Command::Advance(action) => Some(usize::from(action)),
            Command::Auto(remaining) => {
                let start = Instant::now();
                // Keep the real actor and both critics on the original inspect path.
                // Its decoder/head work is included here, never counted a second time.
                let inspection = model.inspect(&state.model, f64::from(remaining) / 1_000_000.0)?;
                let law = inspection.get("policy.probabilities")?;
                let maximum = law.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                let selected = law
                    .iter()
                    .position(|value| *value == maximum)
                    .ok_or("empty policy")?;
                phases[3] = elapsed(start)?;
                Some(selected)
            }
            Command::Init(_) | Command::Commit { .. } => None,
        };
        if let Some(action) = action {
            let start = Instant::now();
            state.model = model.advance(
                &state.model,
                ACTIONS.get(action).ok_or("invalid selected action")?,
                public,
            )?;
            phases[2] = elapsed(start)?;
        }
        let mut delta = Vec::new();
        let commits: Vec<(u8, u32)> = if state.model.stopped {
            TOTAL_UNITS
                .iter()
                .enumerate()
                .filter_map(|(index, total)| {
                    let remaining = total - state.prefixes.cursors[index];
                    (remaining > 0).then_some((index as u8, remaining))
                })
                .collect()
        } else if let Command::Commit { modality, units } = request.command {
            vec![(modality, units)]
        } else {
            Vec::new()
        };
        for (modality, units) in commits {
            let start = Instant::now();
            let payload = chunk(
                model,
                &state.model,
                modality,
                state.prefixes.cursors[usize::from(modality)],
                units,
                state.law,
            )?;
            phases[2] = phases[2]
                .checked_add(elapsed(start)?)
                .ok_or("inference timer overflow")?;
            let start = Instant::now();
            delta.extend(state.prefixes.frame(modality, units, &payload)?);
            phases[0] = phases[0]
                .checked_add(elapsed(start)?)
                .ok_or("codec timer overflow")?;
        }
        let start = Instant::now();
        if delta.len() > MAX_DELTA_BYTES {
            return Err("delta exceeds bridge bound".into());
        }
        let mut prefix = request.prefix.to_vec();
        prefix.extend(&delta);
        if prefix.len() > MAX_PREFIX_BYTES {
            return Err("prefix exceeds bridge bound".into());
        }
        let successor = state.encode(weights_hash, input_hash, &prefix)?;
        phases[0] = phases[0]
            .checked_add(elapsed(start)?)
            .ok_or("codec timer overflow")?;
        Ok(Response {
            digest: request.digest,
            stopped: state.model.stopped,
            phase_micros: phases,
            state: successor,
            delta,
        })
    }
}

pub(crate) fn propose(bytes: &[u8]) -> Result<Response> {
    let codec_start = Instant::now();
    let request = parse(bytes)?;
    let loaded = LoadedModel::load(request.weights, request.public)?;
    loaded.propose(request, codec_start)
}

fn canonical_packet(bytes: &[u8]) -> Result<Packet> {
    let packet = Packet::decode(bytes)?;
    if packet.encode()? != bytes {
        return Err("noncanonical asset packet".into());
    }
    Ok(packet)
}

fn elapsed(start: Instant) -> Result<u64> {
    u64::try_from(start.elapsed().as_micros()).map_err(|_| "phase timer overflow".into())
}
