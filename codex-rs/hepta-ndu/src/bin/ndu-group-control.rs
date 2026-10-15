//! Bounded online research control using native utility arithmetic, without effects.
use std::error::Error;
use std::io::Read;

use codex_hepta_ndu::RecursiveUtilityPath;
use codex_hepta_ndu::UtilityEvent;
use codex_hepta_ndu::evaluate_recursive_utility;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

const Q: i128 = 1_i128 << 32;
const SCHEMA: &str = "hepta.ndu.group-control.v1";

fn main() -> Result<(), Box<dyn Error>> {
    let mut input = String::new();
    std::io::stdin().take(16_385).read_to_string(&mut input)?;
    if input.len() > 16_384 || !input.is_ascii() || input.contains('\r') || !input.ends_with('\n') {
        return Err("bounded ASCII control request required".into());
    }
    let lines = input.lines().collect::<Vec<_>>();
    if !(4..=19).contains(&lines.len()) || lines[0] != SCHEMA {
        return Err("versioned request with 1..16 scenarios required".into());
    }
    for line in &lines {
        if line.split_ascii_whitespace().collect::<Vec<_>>().join(" ") != *line {
            return Err("canonical whitespace required".into());
        }
    }
    let header = lines[1].split(' ').collect::<Vec<_>>();
    if header.len() != 21 || header[0] != "context" {
        return Err("complete observable control context required".into());
    }
    let identities = header[1..10]
        .iter()
        .map(|value| nonzero_digest(value))
        .collect::<Result<Vec<_>, _>>()?;
    let generation: u64 = header[10].parse()?;
    let as_of: u64 = header[11].parse()?;
    let cutoff: u64 = header[12].parse()?;
    let observed: u64 = header[13].parse()?;
    let expires: u64 = header[14].parse()?;
    let stop: i64 = header[15].parse()?;
    let margin: i64 = header[16].parse()?;
    let lower: i64 = header[17].parse()?;
    let upper: i64 = header[18].parse()?;
    let remaining_work: u64 = header[19].parse()?;
    let remaining_wall: u64 = header[20].parse()?;
    if generation == 0
        || cutoff == 0
        || cutoff >= as_of
        || !(cutoff <= observed && observed <= as_of && as_of < expires)
        || margin < 0
        || lower >= upper
        || lower > 0
        || upper < 0
        || stop < lower
        || stop > upper
    {
        return Err("invalid fixed context, filtration or utility domain".into());
    }
    let footer_line = lines.last().ok_or("missing digest")?;
    let footer = footer_line.split(' ').collect::<Vec<_>>();
    if footer.len() != 2 || footer[0] != "finish" {
        return Err("complete request digest required".into());
    }
    let input_digest = nonzero_digest(footer[1])?;
    let payload_length = input.len() - footer_line.len() - 1;
    if Digest32::of_bytes(&input.as_bytes()[..payload_length]) != input_digest {
        return Err("input digest mismatch".into());
    }
    let mut episode_bytes = b"hepta.ndu.group-control.episode.v1".to_vec();
    episode_bytes.extend_from_slice(input_digest.as_array());
    let episode = Digest32::of_bytes(&episode_bytes);
    let mut scenarios = Vec::new();
    let mut probability_sum = 0_i128;
    let mut expected_numerator = 0_i128;
    let mut unsupported_projection = false;
    let mut infeasible = false;
    for (index, line) in lines[2..lines.len() - 1].iter().enumerate() {
        let fields = line.split(' ').collect::<Vec<_>>();
        if fields.len() != 8 || fields[0] != "scenario" {
            return Err("complete scenario required".into());
        }
        let probability: u64 = fields[1].parse()?;
        let forecast: i64 = fields[2].parse()?;
        let discount: i64 = fields[3].parse()?;
        let compute_cost: i64 = fields[4].parse()?;
        let time_cost: i64 = fields[5].parse()?;
        let work: u64 = fields[6].parse()?;
        let duration: u64 = fields[7].parse()?;
        let cost = compute_cost.checked_add(time_cost).ok_or("cost overflow")?;
        if i128::from(probability) > Q
            || !(0..=Q).contains(&i128::from(discount))
            || compute_cost < 0
            || time_cost < 0
            || forecast < lower
            || forecast > upper
            || -i128::from(cost) < i128::from(lower)
            || duration == 0
        {
            return Err("invalid scenario probability, cost, discount or bounds".into());
        }
        probability_sum += i128::from(probability);
        let mut events = Vec::new();
        for (position, instant, factor) in [(1_u64, -cost, discount), (2_u64, forecast, 0)] {
            let mut bytes = b"hepta.ndu.group-control.event.v1".to_vec();
            bytes.extend_from_slice(input_digest.as_array());
            bytes.extend_from_slice(&(index as u64).to_be_bytes());
            bytes.extend_from_slice(&position.to_be_bytes());
            events.push(UtilityEvent {
                sequence: position,
                event_digest: Digest32::of_bytes(&bytes),
                preference_digest: identities[8],
                instant: FixedQ32::from_raw(instant),
                discount: FixedQ32::from_raw(factor),
            });
        }
        // The artificial terminal is exactly zero. Forecasts are event inputs,
        // never relabelled as an observed task outcome or trusted support.
        let receipt = evaluate_recursive_utility(&RecursiveUtilityPath {
            objective_digest: identities[0],
            episode_digest: episode,
            coefficient_digest: identities[7],
            units_digest: Digest32::of_bytes(b"hepta.ndu.group-control.normalized-utility.q32.v1"),
            terminal_outcome_digest: Digest32::of_bytes(
                b"hepta.ndu.group-control.arithmetic-zero-boundary.v1",
            ),
            terminal: FixedQ32::ZERO,
            lower: FixedQ32::from_raw(lower),
            upper: FixedQ32::from_raw(upper),
            events,
        })?;
        if receipt.authority != AuthorityPosture::DENY_ALL {
            return Err("research control cannot grant authority".into());
        }
        let native = receipt.values[0].raw();
        let projections = receipt.projection_count;
        let conservative = if projections == 0 {
            // Convert the library's nearest rounding to a downward bound.
            let floor = (i128::from(discount) * i128::from(forecast)).div_euclid(Q);
            let guard = i128::from(native) + i128::from(cost) - floor;
            if !(0..=1).contains(&guard) {
                return Err("unexpected native rounding delta".into());
            }
            Some(i64::try_from(i128::from(native) - guard)?)
        } else {
            None
        };
        if probability > 0 {
            unsupported_projection |= conservative.is_none();
            infeasible |= work > remaining_work || duration >= remaining_wall;
            if let Some(value) = conservative {
                expected_numerator += i128::from(probability) * i128::from(value);
            }
        }
        let value_json = conservative.map_or_else(|| "null".to_string(), |value| value.to_string());
        let evidence = receipt.evidence_digest;
        scenarios.push(format!(
            "{{\"probability_q32\":{probability},\"native_value_q32\":{native},\"conservative_value_q32\":{value_json},\"projection_count\":{projections},\"evidence_sha256\":\"{evidence}\"}}"
        ));
    }
    if probability_sum != Q {
        return Err("complete Q32 probability mass required".into());
    }
    let expected = expected_numerator.div_euclid(Q);
    let continues =
        !unsupported_projection && !infeasible && expected > i128::from(stop) + i128::from(margin);
    let reason = if unsupported_projection {
        "scenario_projection_unsupported"
    } else if infeasible {
        "infeasible_continuation"
    } else if continues {
        "supported_net_gain"
    } else {
        "no_supported_net_gain"
    };
    let expected_json = if unsupported_projection {
        "null".to_string()
    } else {
        expected.to_string()
    };
    let scenarios_json = scenarios.join(",");
    println!(
        "{{\"schema\":\"hepta.ndu.group-control-receipt.v1\",\"input_sha256\":\"{input_digest}\",\"expected_lower_q32\":{expected_json},\"stop_upper_q32\":{stop},\"minimum_margin_q32\":{margin},\"continue_computation\":{continues},\"reason\":\"{reason}\",\"scenarios\":[{scenarios_json}],\"terminal_reference_role\":\"arithmetic_zero_boundary_not_observed_outcome\",\"support_certified\":false,\"production_owner_integrated\":false,\"general_fbsde_solved\":false}}"
    );
    Ok(())
}

fn nonzero_digest(value: &str) -> Result<Digest32, Box<dyn Error>> {
    let digest: Digest32 = value.parse()?;
    if digest.is_zero() {
        return Err("nonzero identity required".into());
    }
    Ok(digest)
}
