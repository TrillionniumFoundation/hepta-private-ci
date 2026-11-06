//! Execute the selected real numeric kernel without any persistent owner.

use std::io::Read;
use std::io::Write;
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

pub(crate) fn propose(bytes: &[u8]) -> Result<Response> {
    let codec_start = Instant::now();
    let request = parse(bytes)?;
    let weights = canonical_packet(request.weights)?;
    let model = Model::new(weights)?;
    if model.width != 32 || model.depth != 1 || model.mode != "dual" || model.boundary != "direct" {
        return Err("bridge requires selected width32/depth1/dual/direct profile".into());
    }
    let public = canonical_packet(request.public)?;
    model.validate_input(&public)?;
    let weights_hash = sha256(request.weights);
    let input_hash = sha256(request.public);
    let prior = match request.command {
        Command::Init(_) => {
            if !request.state.is_empty() || !request.prefix.is_empty() {
                return Err("init requires empty state and prefix".into());
            }
            None
        }
        _ => Some(BridgeState::read(
            request.state,
            &model,
            &weights_hash,
            &input_hash,
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
        let encoded = model.encode(&public)?;
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
            &public,
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
            &model,
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
    let successor = state.encode(&weights_hash, &input_hash, &prefix)?;
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
