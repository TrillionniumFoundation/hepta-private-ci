//! Real observed V1 facts through the original qualification-only writer.
//! These unsigned compatibility records are never production qualification.
use std::io::Write;
use std::path::Path;

use codex_hepta_learning_ledger::*;
use codex_hepta_types::{Digest32,FixedQ32,ProbabilityQ32,StableId};
use serde_json::{json,Value};

use crate::stream_io::{file,Result};

pub fn observed_history(mut ledger:DurableLedger,root:&Path,objective:Digest32,
                        context:&Value,weights:Digest32)->Result<(DurableLedger,Value)> {
    let episode=StableId::new("abc4.actual-last-tick")?;
    let support:Digest32=context["observed_record_digest"].as_str().ok_or("Missing actual observation")?.parse()?;
    let abstained=context["abstain"].as_bool().ok_or("Missing actual native gate result")?;
    let gate_support=Digest32::of_bytes(&serde_json::to_vec(context)?);
    let choice=StableId::new(if abstained {"abstain"}else {"admit_neuron_signal"})?;
    let decision=LedgerEvent::Decision(EpisodeDecision {
        record_id:StableId::new("abc4.observed.decision")?,episode_id:episode.clone(),
        objective_digest:objective,policy_id:StableId::new("abc4.completed-tick-native-signal-gate")?,
        candidate_ids:vec![StableId::new("admit_neuron_signal")?,StableId::new("abstain")?],selected_candidate_id:choice,
        selected_propensity:ProbabilityQ32::ONE,completeness:CandidateSetCompleteness::Complete,
        support_digest:gate_support,
    });
    let first=ledger.append_qualification(Digest32::ZERO,decision)?;
    let outcome=LedgerEvent::Outcome(OutcomeObservation {
        record_id:StableId::new("abc4.observed.outcome")?,outcome_id:StableId::new("abc4.actual-terminal-utility")?,
        episode_id:episode,observer_id:StableId::new("local.research.primary-observer")?,
        value:FixedQ32::from_raw(context["ndu_terminal_q32"].as_i64().ok_or("Missing observed utility")?),
        finality:OutcomeFinality::Terminal,support_digest:support,
    });
    let last=ledger.append_qualification(first.chain_digest,outcome)?;
    let anchor=LedgerAnchor {sequence:last.sequence.get(),chain_digest:last.chain_digest};
    let record=json!({"schema":"hepta.abc4.observed-qualification-ledger.v1",
        "api":"DurableLedger::append_qualification","cargo_feature":"qualification-legacy-write",
        "records":2,"first_chain_digest":first.chain_digest.to_string(),"head_digest":last.chain_digest.to_string(),
        "actual_observation_digest":support.to_string(),"actual_native_anchor":context["anchor"],
        "actual_native_gate_context_digest":gate_support.to_string(),"actual_abstain":abstained,
        "resident_weights_digest":weights.to_string(),
        "actual_native_sequence":context["sequence"],"actual_source_pair":context["source_pair_digest"],
        "production_signed_records":0,"activated_root_trust":false,"production_qualified":false,
        "decision_boundary":"complete binary gate for this actually completed native tick: admit_neuron_signal or reserved abstain; excludes head choice, bootstrap/model errors, multimodal actions and plasticity proposals",
        "causal_credit_claim":false,"upstream_utility_was_not_caused_by_the_head_call":true,
        "scope":"historical V1 same-context observed-history diagnostic; genuine retained observation, no signed authority or causal-return claim"});
    let bytes=serde_json::to_vec_pretty(&record)?;
    let mut witness=std::fs::File::create_new(root.join("learning.research-witness.json"))?;
    witness.write_all(&bytes)?;witness.sync_all()?;drop(witness);drop(ledger);
    let recovered=DurableLedger::recover(file(&root.join("learning.ledger"))?,objective,8,LedgerRecovery::Acknowledged(anchor))?;
    if recovered.records()?.len()!=2 || recovered.snapshot()?.head_digest!=last.chain_digest {
        return Err("Real observed ledger recovery mismatch".into());
    }
    Ok((recovered,record))
}
