//! Executable, one-arm-per-process same-Q24-input mechanism resource probe.
//!
//! This is NOT a real trained model, authenticated deployment, inference worker,
//! production scheduler, NDU decision or source of longitudinal utility evidence.
//! Reports explicitly mark the fixture weights and input as UNVERIFIED. Host
//! CPU/RSS/p99 numbers are not comparable across different physical machines.

use std::env;
use std::fs;
use std::time::Instant;

use codex_hepta_neuron::ActivationPopulationV2;
use codex_hepta_neuron::DiagonalSsmCheckpointV1;
use codex_hepta_neuron::DiagonalSsmConfigV1;
use codex_hepta_neuron::GatedSparseCheckpointV3;
use codex_hepta_neuron::GatedSparseConfigV3;
use codex_hepta_neuron::InhibitoryEdge;
use codex_hepta_neuron::LowRankMinGruCheckpointV1;
use codex_hepta_neuron::LowRankMinGruConfigV1;
use codex_hepta_neuron::PopulationSparseCheckpointV2;
use codex_hepta_neuron::PopulationSparseConfigV2;
use codex_hepta_neuron::PopulationSparseTickV2;
use codex_hepta_neuron::PreparedDiagonalSsmConfigV1;
use codex_hepta_neuron::PreparedGatedSparseConfigV3;
use codex_hepta_neuron::PreparedLowRankMinGruConfigV1;
use codex_hepta_neuron::PreparedPopulationSparseConfigV2;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::TemporalGateV3;
use codex_hepta_neuron::TemporalProjectionEdgeV2;
use codex_hepta_neuron::diagonal_ssm_tick_v1;
use codex_hepta_neuron::gated_sparse_tick_v3;
use codex_hepta_neuron::low_rank_min_gru_tick_v1;
use codex_hepta_neuron::population_sparse_tick_v2;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde_json::json;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_EVENTS: usize = 1_024;
const ALLOWED_CELLS: &[usize] = &[64, 256, 1_024, 4_096];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MechanismTraceV1 {
    schema: String,
    width: usize,
    events: Vec<TraceEvent>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TraceEvent {
    sequence: u64,
    monotonic_micros: u64,
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
}

// The process owns exactly ONE selected model configuration and ONE mode.
// Never materialize all five models or both legacy and prepared simultaneously.
enum Configs {
    V1(SparseConfig),
    V2Legacy(PopulationSparseConfigV2),
    V2Prepared(PreparedPopulationSparseConfigV2),
    V3Legacy(GatedSparseConfigV3),
    V3Prepared(PreparedGatedSparseConfigV3),
    SsmLegacy(DiagonalSsmConfigV1),
    SsmPrepared(PreparedDiagonalSsmConfigV1),
    MinGruLegacy(Box<LowRankMinGruConfigV1>, usize),
    MinGruPrepared(Box<PreparedLowRankMinGruConfigV1>, usize),
}

impl Configs {
    fn temporal_parameter_count_only(&self) -> Option<usize> {
        match self {
            Self::MinGruLegacy(_, value) | Self::MinGruPrepared(_, value) => Some(*value),
            _ => None,
        }
    }

    #[cfg(test)]
    fn is_prepared(&self) -> bool {
        matches!(
            self,
            Self::V2Prepared(_)
                | Self::V3Prepared(_)
                | Self::SsmPrepared(_)
                | Self::MinGruPrepared(_)
        )
    }
}

enum ActiveState {
    V1(Vec<Option<SparseCheckpoint>>),
    V2(Vec<Option<PopulationSparseCheckpointV2>>),
    V3(Vec<Option<GatedSparseCheckpointV3>>),
    Ssm(Vec<Option<DiagonalSsmCheckpointV1>>),
    MinGru(Vec<Option<LowRankMinGruCheckpointV1>>),
}

impl ActiveState {
    fn new(arm: &str, cells: usize) -> Result<Self, String> {
        match arm {
            "v1" => Ok(Self::V1(vec![None; cells])),
            "v2" => Ok(Self::V2(vec![None; cells])),
            "v3" => Ok(Self::V3(vec![None; cells])),
            "ssm" => Ok(Self::Ssm(vec![None; cells])),
            "min_gru" => Ok(Self::MinGru(vec![None; cells])),
            _ => Err("arm must be v1, v2, v3, ssm or min_gru".to_owned()),
        }
    }

    fn apply(
        &mut self,
        cell: usize,
        input: &PopulationSparseTickV2,
        config: &Configs,
    ) -> Result<Digest32, String> {
        match (self, config) {
            (Self::V1(states), Configs::V1(cfg)) => {
                let tick = SparseTick {
                    scope_digest: input.scope_digest,
                    objective_digest: input.objective_digest,
                    ndu_digest: input.ndu_digest,
                    body_digest: input.body_digest,
                    input_digest: input.input_digest,
                    sequence: input.sequence,
                    monotonic_micros: input.monotonic_micros,
                    drive_q24: input.temporal_drive_q24.clone(),
                    prediction_q24: input.prediction_q24.clone(),
                };
                let (next, receipt) = sparse_tick(cfg, &tick, states[cell].as_ref())
                    .map_err(|error| format!("V1 tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::V2(states), Configs::V2Legacy(cfg)) => {
                let (next, receipt) = population_sparse_tick_v2(cfg, input, states[cell].as_ref())
                    .map_err(|error| format!("V2 legacy tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::V2(states), Configs::V2Prepared(cfg)) => {
                let (next, receipt) = cfg
                    .tick(input, states[cell].as_ref())
                    .map_err(|error| format!("V2 prepared tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::V3(states), Configs::V3Legacy(cfg)) => {
                let (next, receipt) = gated_sparse_tick_v3(cfg, input, states[cell].as_ref())
                    .map_err(|error| format!("V3 legacy tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::V3(states), Configs::V3Prepared(cfg)) => {
                let (next, receipt) = cfg
                    .tick(input, states[cell].as_ref())
                    .map_err(|error| format!("V3 prepared tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::Ssm(states), Configs::SsmLegacy(cfg)) => {
                let (next, receipt) = diagonal_ssm_tick_v1(cfg, input, states[cell].as_ref())
                    .map_err(|error| format!("SSM legacy tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::Ssm(states), Configs::SsmPrepared(cfg)) => {
                let (next, receipt) = cfg
                    .tick(input, states[cell].as_ref())
                    .map_err(|error| format!("SSM prepared tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::MinGru(states), Configs::MinGruLegacy(cfg, _)) => {
                let (next, receipt) =
                    low_rank_min_gru_tick_v1(cfg, input, states[cell].as_ref())
                        .map_err(|error| format!("minGRU legacy tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            (Self::MinGru(states), Configs::MinGruPrepared(cfg, _)) => {
                let (next, receipt) = cfg
                    .tick(input, states[cell].as_ref())
                    .map_err(|error| format!("minGRU prepared tick rejected: {error:?}"))?;
                states[cell] = Some(next);
                Ok(receipt.checkpoint_after)
            }
            _ => Err("model configuration does not match this Cell state".to_owned()),
        }
    }
}

// Only construct a single selected arm and mode. In particular, never
// allocate or validate other arms even during cold setup: VmHWM includes
// discarded graph allocations and would misrepresent model residency.
fn make_configs(width: usize, arm: &str, prepared: bool) -> Result<Configs, String> {
    let model_digest = Digest32::of_bytes(b"fixture-untrained-mechanism-model");
    let normalization_digest = Digest32::of_bytes(b"fixture-q24-normalization");
    let generation = Generation::new(1).map_err(|error| format!("{error:?}"))?;
    let global_top_k = (width / 10).max(1);
    if arm == "v1" {
        let cfg = SparseConfig {
            model_digest,
            normalization_digest,
            generation,
            width,
            top_k: global_top_k,
            temporal_decay_q24: Q / 2,
            inhibition_gain_q24: Q / 2,
            inhibition: Vec::<InhibitoryEdge>::new(),
            activity_decay_q24: Q / 2,
            target_activity_q24: Q / 2,
            threshold_rate_q24: Q / 16,
            threshold_min_q24: -Q,
            threshold_max_q24: Q,
            eligibility_decay_q24: Q / 2,
        };
        cfg.digest()
            .map_err(|error| format!("V1 config: {error:?}"))?;
        return Ok(Configs::V1(cfg));
    }
    if !["v2", "v3", "ssm", "min_gru"].contains(&arm) {
        return Err("unknown fixture mechanism arm".to_owned());
    }

    let split = width / 2;
    let first_k = global_top_k.div_ceil(2);
    let second_k = (global_top_k / 2).max(1);
    let base = PopulationSparseConfigV2 {
        model_digest,
        normalization_digest,
        generation,
        temporal_width: width,
        activation_width: width,
        global_top_k,
        temporal_decay_q24: Q / 2,
        projection: (0..width)
            .map(|index| TemporalProjectionEdgeV2 {
                source_temporal: index,
                target_activation: index,
                weight_q24: Q,
            })
            .collect(),
        inhibition_gain_q24: Q / 2,
        inhibition: Vec::new(),
        populations: vec![
            ActivationPopulationV2 {
                start: 0,
                len: split,
                top_k: first_k,
            },
            ActivationPopulationV2 {
                start: split,
                len: width - split,
                top_k: second_k,
            },
        ],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 2,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    match arm {
        "v2" => {
            if prepared {
                Ok(Configs::V2Prepared(
                    PreparedPopulationSparseConfigV2::new(base)
                        .map_err(|error| format!("prepared V2: {error:?}"))?,
                ))
            } else {
                base.digest()
                    .map_err(|error| format!("V2 config: {error:?}"))?;
                Ok(Configs::V2Legacy(base))
            }
        }
        "v3" => {
            let cfg = GatedSparseConfigV3 {
                base,
                gates: vec![
                    TemporalGateV3 {
                        bias_q24: Q / 2,
                        input_gain_q24: Q / 4,
                        change_gain_q24: Q / 8,
                    };
                    width
                ],
            };
            if prepared {
                Ok(Configs::V3Prepared(
                    PreparedGatedSparseConfigV3::new(cfg)
                        .map_err(|error| format!("prepared V3: {error:?}"))?,
                ))
            } else {
                cfg.digest()
                    .map_err(|error| format!("V3 config: {error:?}"))?;
                Ok(Configs::V3Legacy(cfg))
            }
        }
        "ssm" => {
            let cfg = DiagonalSsmConfigV1 {
                base,
                decay_per_step_q24: vec![Q / 2; width],
                input_gain_q24: vec![Q / 2; width],
                time_quantum_micros: 100,
            };
            if prepared {
                Ok(Configs::SsmPrepared(
                    PreparedDiagonalSsmConfigV1::new(cfg)
                        .map_err(|error| format!("prepared SSM: {error:?}"))?,
                ))
            } else {
                cfg.digest()
                    .map_err(|error| format!("SSM config: {error:?}"))?;
                Ok(Configs::SsmLegacy(cfg))
            }
        }
        "min_gru" => {
            let cfg = LowRankMinGruConfigV1 {
                base,
                rank: 1,
                gate_input_q24: vec![0; width],
                gate_output_q24: vec![0; width],
                candidate_input_q24: vec![0; width],
                candidate_output_q24: vec![0; width],
                gate_bias_q24: vec![0; width],
                candidate_bias_q24: vec![0; width],
            };
            let params = cfg
                .temporal_parameter_count()
                .map_err(|error| format!("minGRU count: {error:?}"))?;
            if prepared {
                Ok(Configs::MinGruPrepared(
                    Box::new(
                        PreparedLowRankMinGruConfigV1::new(cfg)
                            .map_err(|error| format!("prepared minGRU: {error:?}"))?,
                    ),
                    params,
                ))
            } else {
                cfg.digest()
                    .map_err(|error| format!("minGRU config: {error:?}"))?;
                Ok(Configs::MinGruLegacy(Box::new(cfg), params))
            }
        }
        _ => Err("unknown fixture mechanism arm".to_owned()),
    }
}

fn parse_trace(bytes: &[u8]) -> Result<MechanismTraceV1, String> {
    let trace: MechanismTraceV1 =
        serde_json::from_slice(bytes).map_err(|error| format!("invalid trace JSON: {error}"))?;
    if trace.schema != "hepta.neuron.mechanism-probe-trace.q24.v1"
        || !(5..=256).contains(&trace.width)
        || trace.events.is_empty()
        || trace.events.len() > MAX_EVENTS
    {
        return Err("invalid trace schema, width or bounded event count".to_owned());
    }
    let mut previous_micros = 0;
    for (index, row) in trace.events.iter().enumerate() {
        if row.sequence != (index + 1) as u64
            || row.monotonic_micros <= previous_micros
            || row.drive_q24.len() != trace.width
            || row.prediction_q24.len() != trace.width
            || row
                .drive_q24
                .iter()
                .chain(&row.prediction_q24)
                .any(|value| !(-H..=H).contains(value))
        {
            return Err(format!(
                "invalid sequence, clock, Q24 bounds or dimensions at event {index}"
            ));
        }
        previous_micros = row.monotonic_micros;
    }
    Ok(trace)
}

fn request_for(row: &TraceEvent, cell: usize) -> PopulationSparseTickV2 {
    let mut event_bytes = Vec::with_capacity(16 + (row.drive_q24.len() * 16));
    event_bytes.extend_from_slice(&row.sequence.to_be_bytes());
    event_bytes.extend_from_slice(&row.monotonic_micros.to_be_bytes());
    for value in row.drive_q24.iter().chain(&row.prediction_q24) {
        event_bytes.extend_from_slice(&value.to_be_bytes());
    }
    PopulationSparseTickV2 {
        scope_digest: Digest32::of_parts(&[
            b"hepta.neuron.probe-cell-scope.v1",
            &(cell as u64).to_be_bytes(),
        ]),
        objective_digest: Digest32::of_bytes(b"probe-objective"),
        ndu_digest: Digest32::of_bytes(b"unverified-ndu-probe"),
        body_digest: Digest32::of_bytes(b"probe-body"),
        input_digest: Digest32::of_bytes(&event_bytes),
        sequence: row.sequence,
        monotonic_micros: row.monotonic_micros,
        temporal_drive_q24: row.drive_q24.clone(),
        prediction_q24: row.prediction_q24.clone(),
    }
}

fn percentile(sorted: &[u64], pct: usize) -> u64 {
    let index = ((sorted.len() * pct).div_ceil(100)).saturating_sub(1);
    sorted[index]
}

fn process_peak_rss_bytes() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let value = line.strip_prefix("VmHWM:")?;
        value
            .split_whitespace()
            .next()?
            .parse::<u64>()
            .ok()?
            .checked_mul(1_024)
    })
}

fn parse_prepared_mode(value: &str) -> Result<bool, String> {
    match value {
        "prepared" => Ok(true),
        "legacy" => Ok(false),
        _ => Err("mode must be legacy or prepared".to_owned()),
    }
}

fn run() -> Result<(), String> {
    let mut arm = None;
    let mut cells = None;
    let mut trace_path = None;
    let mut mode = "prepared".to_owned();
    let mut args = env::args().skip(1);
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        match flag.as_str() {
            "--arm" => arm = Some(value),
            "--cells" => {
                cells = Some(
                    value
                        .parse::<usize>()
                        .map_err(|_| "cells must be an integer".to_owned())?,
                )
            }
            "--trace" => trace_path = Some(value),
            "--mode" => mode = value,
            _ => return Err(format!("unrecognized parameter {flag}")),
        }
    }
    let arm = arm.ok_or("required --arm")?;
    let cells = cells.ok_or("required --cells")?;
    let trace_path = trace_path.ok_or("required --trace")?;
    let prepared_mode = parse_prepared_mode(&mode)?;
    if !ALLOWED_CELLS.contains(&cells) {
        return Err("Cell count must be 64, 256, 1024 or 4096".to_owned());
    }
    let bytes = fs::read(trace_path).map_err(|error| format!("trace file: {error}"))?;
    let trace_digest = Digest32::of_bytes(&bytes);
    let trace = parse_trace(&bytes)?;
    let preparation_started = Instant::now();
    let configs = make_configs(trace.width, &arm, prepared_mode)?;
    let model_config_setup_micros =
        u64::try_from(preparation_started.elapsed().as_micros()).unwrap_or(u64::MAX);
    let mut states = ActiveState::new(&arm, cells)?;
    let mut frontiers = vec![Digest32::ZERO; cells];
    let mut samples = Vec::with_capacity(cells * trace.events.len());

    let whole_start = Instant::now();
    for row in &trace.events {
        for (cell, frontier) in frontiers.iter_mut().enumerate() {
            let input = request_for(row, cell);
            let started = Instant::now();
            let digest = states.apply(cell, &input, &configs)?;
            let nanos = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
            samples.push(nanos);
            *frontier = digest;
        }
    }
    let wall_ns = u64::try_from(whole_start.elapsed().as_nanos()).unwrap_or(u64::MAX);
    samples.sort_unstable();
    let mut bound = b"hepta.neuron.mechanism-probe-frontiers.v1".to_vec();
    for digest in &frontiers {
        bound.extend_from_slice(digest.as_array());
    }
    let total_ticks = samples.len() as u64;
    let report = json!({
        "schema": "hepta.neuron.mechanism-resource-probe.v1",
        "evidence_kind": "UNVERIFIED_KERNEL_ONLY_NOT_TARGET_HOST_ACCEPTANCE",
        "production_qualification": false,
        "ndu_eligible": false,
        "trained_model": false,
        "all_model_parameter_budgets_matched": false,
        "temporal_parameter_count_only": configs.temporal_parameter_count_only(),
        "single_selected_config_resident": true,
        "simultaneous_legacy_and_prepared_config_resident": false,
        "model_config_setup_micros": model_config_setup_micros,
        "state_persistence_measured": false,
        "microbatch_and_gpu_measured": false,
        "artifact_provenance_verified": false,
        "arm": arm,
        "execution_mode": mode,
        "cells": cells,
        "width": trace.width,
        "trace_sha256": trace_digest.to_string(),
        "logical_tick_count": total_ticks,
        "process_wall_micros": wall_ns / 1_000,
        "p50_tick_nanos": percentile(&samples, 50),
        "p95_tick_nanos": percentile(&samples, 95),
        "p99_tick_nanos": percentile(&samples, 99),
        "p50_tick_micros": (percentile(&samples, 50) as f64) / 1000.0,
        "p95_tick_micros": (percentile(&samples, 95) as f64) / 1000.0,
        "p99_tick_micros": (percentile(&samples, 99) as f64) / 1000.0,
        "process_peak_rss_bytes": process_peak_rss_bytes(),
        "mechanism_tick_throughput_per_second_milli": total_ticks
            .saturating_mul(1_000_000_000_000)
            .checked_div(wall_ns.max(1)).unwrap_or(0),
        "frontier_digest": Digest32::of_bytes(&bound).to_string(),
        "warning": "one arm per process; fixed synthetic untrained parameters; source trace is not independently authenticated"
    });
    println!("{report}");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("BLOCKED_MECHANISM_PROBE: {error}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_trace() -> MechanismTraceV1 {
        MechanismTraceV1 {
            schema: "hepta.neuron.mechanism-probe-trace.q24.v1".to_owned(),
            width: 32,
            events: vec![
                TraceEvent {
                    sequence: 1,
                    monotonic_micros: 100,
                    drive_q24: vec![Q / 2; 32],
                    prediction_q24: vec![0; 32],
                },
                TraceEvent {
                    sequence: 2,
                    monotonic_micros: 200,
                    drive_q24: vec![Q; 32],
                    prediction_q24: vec![0; 32],
                },
            ],
        }
    }

    fn bytes(trace: &MechanismTraceV1) -> Vec<u8> {
        let events = trace
            .events
            .iter()
            .map(|event| {
                json!({
                    "sequence": event.sequence,
                    "monotonic_micros": event.monotonic_micros,
                    "drive_q24": event.drive_q24,
                    "prediction_q24": event.prediction_q24,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_vec(&json!({
            "schema": trace.schema,
            "width": trace.width,
            "events": events,
        }))
        .expect("test trace serialization")
    }

    #[test]
    fn every_arm_accepts_same_trace_with_exactly_one_selected_mode() {
        let trace = parse_trace(&bytes(&sample_trace())).expect("valid 32D two-tick trace");
        let v1 = make_configs(trace.width, "v1", false).expect("V1");
        let v2 = make_configs(trace.width, "v2", false).expect("V2");
        match (&v1, &v2) {
            (Configs::V1(a), Configs::V2Legacy(b)) => {
                assert_ne!(a.digest().expect("V1"), b.digest().expect("V2"));
                assert_eq!(b.populations.len(), 2);
                assert_eq!(b.global_top_k, 3);
            }
            _ => panic!("incorrect selected model"),
        }
        for arm in ["v1", "v2", "v3", "ssm", "min_gru"] {
            for mode in [false, true] {
                let config = make_configs(trace.width, arm, mode).expect("one selected model");
                assert_eq!(config.is_prepared(), mode && arm != "v1");
                let mut states = ActiveState::new(arm, 64).expect("valid arm");
                for row in &trace.events {
                    let input = request_for(row, 7);
                    let frontier = states
                        .apply(7, &input, &config)
                        .expect("arm must process same Q24 trace");
                    assert!(!frontier.is_zero());
                }
            }
        }
    }

    #[test]
    fn mismatched_selected_model_and_checkpoint_state_reject() {
        let sample = sample_trace();
        let input = request_for(&sample.events[0], 7);
        let v2_legacy = make_configs(32, "v2", false).expect("V2 legacy");
        let v2_prepared = make_configs(32, "v2", true).expect("V2 prepared");
        assert!(matches!(v2_legacy, Configs::V2Legacy(_)));
        assert!(matches!(v2_prepared, Configs::V2Prepared(_)));
        assert!(make_configs(32, "unknown", true).is_err());
        let mut v3 = ActiveState::new("v3", 64).expect("V3");
        assert!(v3.apply(7, &input, &v2_prepared).is_err());
        let mut ssm = ActiveState::new("ssm", 64).expect("SSM");
        assert!(ssm.apply(7, &input, &v2_legacy).is_err());
    }

    #[test]
    fn isolated_legacy_and_prepared_modes_produce_identical_frontiers() {
        let trace = parse_trace(&bytes(&sample_trace())).expect("valid input");
        for arm in ["v1", "v2", "v3", "ssm", "min_gru"] {
            let mut frontier = Vec::new();
            for mode in [false, true] {
                let config = make_configs(trace.width, arm, mode).expect("one selected model");
                let mut state = ActiveState::new(arm, 64).expect("model state");
                let mut latest = Digest32::ZERO;
                for row in &trace.events {
                    latest = state
                        .apply(7, &request_for(row, 7), &config)
                        .expect("same Q24 input");
                }
                frontier.push(latest);
            }
            assert_eq!(
                frontier[0], frontier[1],
                "{arm}: different checkpoint digest"
            );
        }
    }

    #[test]
    fn trace_schema_clock_sequence_and_bounds_fail_closed() {
        let mut trace = sample_trace();
        trace.events[1].sequence = 3;
        assert!(parse_trace(&bytes(&trace)).is_err());
        trace = sample_trace();
        trace.events[1].monotonic_micros = 100;
        assert!(parse_trace(&bytes(&trace)).is_err());
        trace = sample_trace();
        trace.events[1].drive_q24[0] = H + 1;
        assert!(parse_trace(&bytes(&trace)).is_err());
        trace = sample_trace();
        trace.width = 256;
        assert!(parse_trace(&bytes(&trace)).is_err());
        trace = sample_trace();
        trace.schema = "unknown".to_owned();
        assert!(parse_trace(&bytes(&trace)).is_err());
        assert!(parse_trace(b"{}").is_err());
    }

    #[test]
    fn only_preregistered_cell_scales_and_known_arm_identifiers_are_valid() {
        for n in ALLOWED_CELLS {
            assert!(ActiveState::new("v1", *n).is_ok());
        }
        assert!(ActiveState::new("unknown", 64).is_err());
        assert_eq!(ALLOWED_CELLS, &[64, 256, 1024, 4096]);
    }
}
