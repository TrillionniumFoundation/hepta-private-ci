//! Offline scalar utility replay composition. No owner, effects or general FBSDE.

use std::error::Error;
use std::io::Read;

use codex_hepta_ndu::RecursiveUtilityPath;
use codex_hepta_ndu::UtilityEvent;
use codex_hepta_ndu::evaluate_recursive_utility;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

const MAX_INPUT_BYTES: u64 = 131_072;
const SCHEMA: &str = "hepta.ndu.group-replay.v1";

fn main() -> Result<(), Box<dyn Error>> {
    let mut input = String::new();
    std::io::stdin()
        .take(MAX_INPUT_BYTES + 1)
        .read_to_string(&mut input)?;
    if input.len() > MAX_INPUT_BYTES as usize
        || !input.is_ascii()
        || input.contains('\r')
        || !input.ends_with('\n')
    {
        return Err("bounded newline-terminated ASCII replay required".into());
    }
    let lines = input.lines().collect::<Vec<_>>();
    if !(4..=515).contains(&lines.len()) || lines[0] != SCHEMA {
        return Err("versioned bounded nonempty replay required".into());
    }
    for line in &lines {
        if line.split_ascii_whitespace().collect::<Vec<_>>().join(" ") != *line {
            return Err("noncanonical replay whitespace".into());
        }
    }
    let header = lines[1].split(' ').collect::<Vec<_>>();
    if header.len() != 12 || header[0] != "context" {
        return Err("complete fixed replay context required".into());
    }
    let objective = nonzero_digest(header[1])?;
    let subject = nonzero_digest(header[2])?;
    let generation: u64 = header[3].parse()?;
    if generation == 0 {
        return Err("nonzero fixed generation required".into());
    }
    let episode = nonzero_digest(header[4])?;
    let coefficient = nonzero_digest(header[5])?;
    let units = nonzero_digest(header[6])?;
    let outcome = nonzero_digest(header[7])?;
    let observer = nonzero_digest(header[8])?;
    let terminal = FixedQ32::from_raw(header[9].parse()?);
    let lower = FixedQ32::from_raw(header[10].parse()?);
    let upper = FixedQ32::from_raw(header[11].parse()?);

    let last = lines.last().ok_or("missing digest footer")?;
    let footer = last.split(' ').collect::<Vec<_>>();
    if footer.len() != 2 || footer[0] != "finish" {
        return Err("complete input digest required".into());
    }
    let input_digest = nonzero_digest(footer[1])?;
    let payload_length = input.len() - last.len() - 1;
    if Digest32::of_bytes(&input.as_bytes()[..payload_length]) != input_digest {
        return Err("complete replay input digest mismatch".into());
    }
    let mut context_bytes = b"hepta.ndu.group-replay.context.v1".to_vec();
    context_bytes.extend_from_slice(subject.as_array());
    context_bytes.extend_from_slice(&generation.to_be_bytes());
    context_bytes.extend_from_slice(episode.as_array());
    context_bytes.extend_from_slice(observer.as_array());
    let episode_context = Digest32::of_bytes(&context_bytes);
    let mut events = Vec::with_capacity(lines.len() - 3);
    for line in &lines[2..lines.len() - 1] {
        let fields = line.split(' ').collect::<Vec<_>>();
        if fields.len() != 6 || fields[0] != "event" {
            return Err("complete immutable-context event required".into());
        }
        events.push(UtilityEvent {
            sequence: fields[1].parse()?,
            event_digest: nonzero_digest(fields[2])?,
            preference_digest: nonzero_digest(fields[3])?,
            instant: FixedQ32::from_raw(fields[4].parse()?),
            discount: FixedQ32::from_raw(fields[5].parse()?),
        });
    }
    let receipt = evaluate_recursive_utility(&RecursiveUtilityPath {
        objective_digest: objective,
        episode_digest: episode_context,
        coefficient_digest: coefficient,
        units_digest: units,
        terminal_outcome_digest: outcome,
        terminal,
        lower,
        upper,
        events,
    })?;
    if receipt.authority != AuthorityPosture::DENY_ALL {
        return Err("offline replay cannot grant authority".into());
    }
    let values = receipt
        .values
        .iter()
        .map(|value| value.raw().to_string())
        .collect::<Vec<_>>()
        .join(",");
    let projections = receipt.projection_count;
    let evidence = receipt.evidence_digest;
    println!(
        "{{\"schema\":\"hepta.ndu.group-replay-receipt.v1\",\"input_sha256\":\"{input_digest}\",\"episode_context_sha256\":\"{episode_context}\",\"values_q32\":[{values}],\"projection_count\":{projections},\"evidence_sha256\":\"{evidence}\",\"authority\":\"deny_all\",\"native_utility_replay\":true,\"production_owner_integrated\":false,\"general_fbsde_solved\":false}}"
    );
    Ok(())
}

fn nonzero_digest(value: &str) -> Result<Digest32, Box<dyn Error>> {
    let digest: Digest32 = value.parse()?;
    if digest.is_zero() {
        return Err("nonzero identity/outcome reference required".into());
    }
    Ok(digest)
}
