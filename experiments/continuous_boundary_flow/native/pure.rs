//! Long-lived pure original-kernel states for causal batched learning/evaluation.
//! This fast path is explicitly separate from durable Agentd owner execution.
use crate::Result;
use crate::decision;
use crate::model::Features;
use crate::model::Profile;
use crate::model::Stage;
use crate::replay;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Row {
    pub case_id: String,
    pub features: Features,
}
pub struct State {
    subject: StableId,
    scope: JournalScope,
    checkpoint: Option<SparseCheckpoint>,
    terminal: bool,
}
pub type States = BTreeMap<(String, String), State>;
pub fn reset(
    states: &mut States,
    profile: &Profile,
    bundle: Digest32,
    cases: Vec<String>,
) -> Result<Value> {
    if cases.is_empty() || cases.len() > 1024 {
        return Err("Pure reset case limit".into());
    }
    let mut next = Vec::new();
    let mut seen = BTreeSet::new();
    for case in cases {
        if !seen.insert(case.clone()) {
            return Err("Duplicate reset case".into());
        }
        let subject = StableId::new(&case)?;
        let scope = JournalScope {
            scope_digest: Digest32::of_parts(&[bundle.as_array(), subject.as_str().as_bytes()]),
            objective_digest: profile.objective_digest.parse()?,
        };
        next.push((
            (bundle.to_string(), case),
            State {
                subject,
                scope,
                checkpoint: None,
                terminal: false,
            },
        ));
    }
    let added = next
        .iter()
        .filter(|(key, _)| !states.contains_key(key))
        .count();
    if states.len() + added > 16384 {
        return Err("Pure-state cache limit".into());
    }
    let count = next.len();
    for (key, state) in next {
        states.insert(key, state);
    }
    Ok(json!({"reset_cases":count,"actual_kernel_calls":0,"durable_owner_execution":false}))
}
pub fn advance(
    states: &mut States,
    profile: &Profile,
    bundle: Digest32,
    binary: Digest32,
    observations: Vec<Row>,
) -> Result<Value> {
    if observations.is_empty() || observations.len() > 1024 {
        return Err("Pure advance batch limit".into());
    }
    let config = profile.runtime(bundle, binary)?;
    let native = profile.native(bundle)?;
    let mut seen = BTreeSet::new();
    let mut pending = Vec::new();
    let mut result = Vec::new();
    // Reject malformed or stale whole batches before executing any kernel.
    for row in &observations {
        if !seen.insert(row.case_id.clone()) {
            return Err("Duplicate batch case".into());
        }
        let state = states
            .get(&(bundle.to_string(), row.case_id.clone()))
            .ok_or("Pure case needs explicit reset")?;
        if state.terminal
            || state
                .checkpoint
                .as_ref()
                .is_some_and(|p| p.sequence() >= profile.maximum_ticks)
        {
            return Err("Pure case stopped or exhausted".into());
        }
        profile.feature_vector(&row.features)?;
    }
    seen.clear();
    for row in observations {
        let key = (bundle.to_string(), row.case_id.clone());
        if !seen.insert(row.case_id.clone()) {
            return Err("Duplicate batch case".into());
        }
        let state = states.get(&key).ok_or("Pure case needs explicit reset")?;
        if state.terminal {
            return Err("Pure case already stopped".into());
        }
        let before = state.checkpoint.as_ref().map(|p| JournalAnchor {
            sequence: p.sequence(),
            checkpoint_digest: p.digest(),
        });
        let step = before.map_or(1, |a| a.sequence + 1);
        let o = replay::Observation {
            event_id: format!("{}.step.{step}", row.case_id),
            step,
            checkpoint: before
                .map_or(Digest32::ZERO, |a| a.checkpoint_digest)
                .to_string(),
            evidence_digest: Digest32::of_bytes(&serde_json::to_vec(&row.features)?).to_string(),
            features: row.features,
        };
        let request = replay::input(profile, &state.subject, state.scope, before, &o)?;
        let drive = profile.encode(&request.feature_vector_q24)?;
        let tick = replay::kernel_input(&config, state.scope, &request, drive)?;
        let (next, signal) = sparse_tick(&native, &tick, state.checkpoint.as_ref())?;
        let readout = decision::decide(
            profile,
            &signal.activation_q24,
            o.features.continuous.risk_q24,
            next.digest(),
        )?;
        let terminal = profile.stage == Stage::Act && readout.action == "stop";
        let mut receipt = json!({"case_id":row.case_id,"step":step,"event_kind":"continuous_readout",
            "profile_masks":[profile.use_margin,profile.use_risk,profile.use_flow],
            "activation_q24":signal.activation_q24,"readout":readout,"terminal":terminal,
            "checkpoint_before":o.checkpoint,"checkpoint_after":next.digest().to_string(),
            "input_feature_digest":request.input_feature_digest.to_string(),
            "temporal_digest":next.temporal_state_digest().to_string(),"projection_count":signal.projection_count});
        receipt["receipt_digest"] =
            json!(Digest32::of_bytes(&serde_json::to_vec(&receipt)?).to_string());
        result.push(receipt);
        pending.push((key, next, terminal));
    }
    // Compute all proposed successors before publishing any state in this batch.
    for (key, next, terminal) in pending {
        let state = states.get_mut(&key).ok_or("Pure state disappeared")?;
        state.checkpoint = Some(next);
        state.terminal = terminal;
    }
    let count = result.len();
    Ok(
        json!({"rows":result,"actual_kernel_calls":count,"actual_ndu_calls":count,
        "durable_owner_execution":false,"owner_authority":"DENY_ALL","profile_sha256":bundle.to_string()}),
    )
}
