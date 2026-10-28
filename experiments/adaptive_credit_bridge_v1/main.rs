//! Research-domain integration through the unchanged authenticated product writer.
mod auth;
#[allow(dead_code)]
mod original_outcome_credit;
use auth::{HostFixture, NOW, digest, id};
use codex_hepta_learning_ledger::*;
use codex_hepta_types::{Digest32, FixedQ32, ProbabilityQ32};
use original_outcome_credit::{
    ObservedOutcomeRequestV2, OutcomeCreditClosureErrorV2, OutcomeCreditClosureRequestV2,
    append_outcome_credit_v2,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(tag = "command", deny_unknown_fields)]
enum Request {
    Init,
    Status,
    Decision {
        case: String,
        organ: String,
        expected_head: String,
        support_json: String,
    },
    Closure {
        case: String,
        organ: String,
        expected_head: String,
        terminal_checkpoint: String,
        outcome_digest: String,
        reward: f64,
        support_json: String,
        fault: String,
    },
}
fn open_file(path: &Path, create: bool) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(path)?)
}
fn receipt(r: &AppendReceipt) -> Value {
    json!({"disposition":format!("{:?}",r.disposition),"sequence":r.sequence.get(),"event_digest":r.event_digest.to_string(),"chain_digest":r.chain_digest.to_string()})
}
fn status(writer: &LedgerWriter, details: bool) -> Result<Value> {
    let frontier = writer.witness_frontier()?;
    let mut value = json!({"sequence":frontier.anchor.sequence,"head":frontier.anchor.chain_digest.to_string(),"trust_generation":writer.trust_generation(),"trust_distribution_digest":writer.trust_distribution_digest().to_string()});
    if details {
        value["records"]=json!(writer.records()?.into_iter().map(|r| {
            let detail=match &r.event {
                LedgerEvent::AuthenticatedDecisionV2(v)=>json!({"kind":"AuthenticatedDecisionV2","episode":v.episode_id.as_str(),"policy_digest":v.policy_digest.to_string(),"run_snapshot_digest":v.run_snapshot_digest.to_string(),"selected_candidate":v.selected_candidate_id.as_str(),"generator":v.generator_id.as_str(),"support_digest":v.support_digest.to_string(),"authentication_digest":v.authentication_digest.to_string()}),
                LedgerEvent::AuthenticatedOutcomeV2(v)=>json!({"kind":"AuthenticatedOutcomeV2","episode":v.episode_id.as_str(),"outcome":v.outcome_id.as_str(),"observer":v.observer_id.as_str(),"value_q32":v.value.map(|q|q.raw()),"support_digest":v.support_digest.to_string(),"authentication_digest":v.authentication_digest.to_string()}),
                LedgerEvent::CreditBatchV2(v)=>json!({"kind":"CreditBatchV2","episode":v.episode_id.as_str(),"outcome":v.outcome_id.as_str(),"allocator":v.allocator_id.as_str(),"value_q32":v.terminal_outcome.raw(),"residual_q32":v.conservation_residual.raw(),"allocations":v.allocations.iter().map(|a|json!({"organ":a.target_artifact_id.as_str(),"credit_q32":a.credit.raw()})).collect::<Vec<_>>(),"support_digest":v.support_digest.to_string(),"authentication_digest":v.authentication_digest.to_string()}),
                _=>json!({"kind":"unexpected"}),
            };
            json!({"record_id":r.event.record_id().as_str(),"sequence":r.sequence.get(),"predecessor":r.predecessor_chain_digest.to_string(),"event_digest":r.event_digest.to_string(),"chain_digest":r.chain_digest.to_string(),"fact":detail})
        }).collect::<Vec<_>>());
    }
    Ok(value)
}
fn checked_support(fixture: &HostFixture, raw: &str, case: &str, organ: &str) -> Result<Digest32> {
    let v: Value = serde_json::from_str(raw)?;
    if v["case"] != case
        || v["organ"] != organ
        || v["model_sha256"] != fixture.model_sha256
        || v["checkpoint_sha256"] != fixture.trained_checkpoint_sha256
        || v["owner_binary_sha256"] != fixture.owner_binary_sha256
    {
        return Err("Attestation is not bound to this owner/model/checkpoint/case".into());
    }
    Ok(Digest32::of_bytes(raw.as_bytes()))
}
fn handle(root: &Path, request: Request) -> Result<Value> {
    let bytes = std::fs::read(root.join("HOST_FIXTURE.json"))?;
    let fixture: HostFixture = serde_json::from_slice(&bytes)?;
    let binding = Digest32::of_bytes(&bytes);
    let (trust, trust_proof) = fixture.activate()?;
    let fresh = matches!(request, Request::Init);
    let ledger_path = root.join("learning.ledger");
    let witness_path = root.join("learning.witness");
    let (ledger, witness, recovered) = if fresh {
        if ledger_path.exists() || witness_path.exists() {
            return Err("Existing signed ledger cannot be reinitialized".into());
        }
        (
            DurableLedger::create(open_file(&ledger_path, true)?, binding, 256)?,
            LedgerWitnessStore::create(open_file(&witness_path, true)?, binding)?,
            0,
        )
    } else {
        let witness = LedgerWitnessStore::recover(open_file(&witness_path, false)?, binding)?;
        let anchor = witness.frontier()?.anchor;
        let recovery = if anchor.sequence == 0 {
            LedgerRecovery::Unacknowledged
        } else {
            LedgerRecovery::Acknowledged(anchor)
        };
        let ledger =
            DurableLedger::recover(open_file(&ledger_path, false)?, binding, 256, recovery)?;
        let count = ledger.records()?.len();
        (ledger, witness, count)
    };
    let directory = File::open(root)?;
    let mut writer = LedgerWriter::from_durable(ledger, witness, trust, &directory, &directory)?;
    let before = status(&writer, false)?;
    let mut result = match request {
        Request::Init | Request::Status => json!({"accepted":true,"status":status(&writer,true)?}),
        Request::Decision {
            case,
            organ,
            expected_head,
            support_json,
        } => {
            let support = checked_support(&fixture, &support_json, &case, &organ)?;
            let binding = json!({"case":case,"organ":organ,"model_sha256":fixture.model_sha256,"checkpoint_sha256":fixture.trained_checkpoint_sha256,"owner_binary_sha256":fixture.owner_binary_sha256,"support_digest":support.to_string()});
            let candidates = vec![id("abstain")?, id("execute-trained-readout")?];
            let decision = ProductionDecisionV2 {
                record_id: id(&format!("{case}.decision"))?,
                episode_id: id(&case)?,
                run_snapshot_digest: support,
                objective_digest: fixture.objective(),
                policy_digest: fixture.model_sha256.parse()?,
                candidate_ids: candidates.clone(),
                selected_candidate_id: id("execute-trained-readout")?,
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompletenessReceiptV1 {
                    set_id: id(&format!("{case}.admission-candidates"))?,
                    state_digest: support,
                    generator_id: fixture.principal("generator")?.principal_id,
                    generator_code_digest: digest(
                        "adaptive-credit-bridge-explicit-admission-generator.v1",
                    ),
                    grammar_digest: digest("abstain-or-execute-task.v1"),
                    hard_filter_digest: digest("authorized-local-research-only.v1"),
                    truncation_digest: digest("no-admission-candidate-truncation.v1"),
                    candidates_digest: candidate_ids_digest_v2(&candidates),
                    candidate_count: 2,
                    omitted_count_bound: 0,
                    canonical_order_digest: candidate_order_digest_v2(&candidates),
                    complete_for_generator: true,
                },
                support_digest: support,
            };
            let payload = decision_signing_payload_v2(&decision)?;
            let (evidence, proof) = fixture.sign(
                writer.verifier(),
                "generator",
                LearningEvidenceRoleV1::Generator,
                &payload,
                false,
            )?;
            match writer.append_decision(expected_head.parse()?, decision, &evidence, NOW) {
                Ok(r) => {
                    json!({"accepted":true,"binding":binding,"decision":receipt(&r),"signed_evidence":[proof],"typed_append_attempts":1})
                }
                Err(e) => {
                    json!({"accepted":false,"error":format!("{e:?}"),"signed_evidence":[proof],"typed_append_attempts":1})
                }
            }
        }
        Request::Closure {
            case,
            organ,
            expected_head,
            terminal_checkpoint,
            outcome_digest,
            reward,
            support_json,
            fault,
        } => {
            if ![-1.0, 0.05, 1.0].contains(&reward)
                || terminal_checkpoint.parse::<Digest32>()?.is_zero()
                || outcome_digest.parse::<Digest32>()?.is_zero()
                || ![
                    "none",
                    "observer_signature",
                    "credit_signature",
                    "stale_head",
                    "expired",
                ]
                .contains(&fault.as_str())
            {
                return Err("Invalid terminal closure request".into());
            }
            let support = checked_support(&fixture, &support_json, &case, &organ)?;
            let v: Value = serde_json::from_str(&support_json)?;
            if v["terminal_checkpoint"] != terminal_checkpoint
                || v["outcome_digest"] != outcome_digest
                || v["reward"] != reward
                || v["native_terminal"] != true
            {
                return Err("Outcome lacks the committed terminal owner binding".into());
            }
            let binding = json!({"case":case,"organ":organ,"model_sha256":fixture.model_sha256,"checkpoint_sha256":fixture.trained_checkpoint_sha256,"owner_binary_sha256":fixture.owner_binary_sha256,"terminal_checkpoint":terminal_checkpoint,"outcome_digest":outcome_digest,"reward":reward,"support_digest":support.to_string()});
            let value = FixedQ32::from_raw((reward * ((1_u64 << 32) as f64)).round() as i64);
            let outcome = AuthenticatedOutcomeV1 {
                record_id: id(&format!("{case}.outcome-record"))?,
                outcome_id: id(&format!("{case}.outcome"))?,
                episode_id: id(&case)?,
                observer: fixture.principal("observer")?,
                observed_at: Some(40),
                value: Some(value),
                unit_profile_digest: digest("bernoulli-terminal-reward-q32.v1"),
                support_digest: support,
                watermark: OutcomeWatermarkV1 {
                    latest_observable_at: 45,
                    expected_delay_profile_digest: digest(
                        "synthetic-outcome-observed-immediately.v1",
                    ),
                    terminality: OutcomeTerminalityV1::Terminal,
                    censoring_reason: None,
                    correction_predecessor: None,
                    finalized_at: Some(46),
                },
            };
            let payload = outcome_signing_payload_v2(&outcome);
            let (evidence, outcome_proof) = fixture.sign(
                writer.verifier(),
                "observer",
                LearningEvidenceRoleV1::Observer,
                &payload,
                fault == "observer_signature",
            )?;
            let credit = CreditAllocationBatchV1 {
                batch_id: id(&format!("{case}.signed-credit"))?,
                episode_id: id(&case)?,
                outcome_id: outcome.outcome_id.clone(),
                allocator: fixture.principal("allocator")?,
                terminal_outcome: value,
                allocations: vec![CreditAllocationV1 {
                    target_id: id(&organ)?,
                    credit: value,
                }],
                conservation_residual: FixedQ32::ZERO,
                support_digest: support,
                finalized: true,
            };
            let finalized = finalize_credit_batch(credit.clone(), NOW)?;
            let payload = credit_batch_signing_payload_v2(&credit, finalized.batch_digest);
            let (credit_evidence, credit_proof) = fixture.sign(
                writer.verifier(),
                "allocator",
                LearningEvidenceRoleV1::CreditAllocator,
                &payload,
                fault == "credit_signature",
            )?;
            let request = OutcomeCreditClosureRequestV2 {
                outcome: ObservedOutcomeRequestV2 {
                    run_id: id(&format!("{case}.decision"))?,
                    expected_ledger_head: if fault == "stale_head" {
                        digest("deliberately-stale-local-research-head")
                    } else {
                        expected_head.parse()?
                    },
                    outcome,
                    evidence,
                },
                credit,
                credit_evidence,
            };
            match append_outcome_credit_v2(
                &mut writer,
                request,
                if fault == "expired" { 100 } else { NOW },
            ) {
                Ok(r) => {
                    if r.authority.grants_any() {
                        return Err("Unexpected ledger authority".into());
                    }
                    json!({"accepted":true,"binding":binding,"outcome":receipt(&r.outcome),"credit":receipt(&r.credit),"closure_digest":r.closure_digest.to_string(),"authority":"DENY_ALL","signed_evidence":[outcome_proof,credit_proof],"typed_append_attempts":2,"resource_settlement_authorized":true})
                }
                Err(e) => {
                    let (partial, attempts) = match &e {
                        OutcomeCreditClosureErrorV2::Credit { outcome, .. } => {
                            (Some(receipt(outcome)), 2)
                        }
                        _ => (None, 1),
                    };
                    json!({"accepted":false,"error":format!("{e:?}"),"partial_outcome":partial,"signed_evidence":[outcome_proof,credit_proof],"typed_append_attempts":attempts,"resource_settlement_authorized":false})
                }
            }
        }
    };
    let after = status(&writer, false)?;
    result["before"] = before.clone();
    result["after"] = after.clone();
    result["new_signed_facts"] = json!(
        after["sequence"].as_u64().ok_or("after sequence")?
            - before["sequence"].as_u64().ok_or("before sequence")?
    );
    result["ledger_recovery_records"] = json!(recovered);
    result["root_signature_activations"] = json!(1);
    result["trust_proof"] = trust_proof;
    result["binding_digest"] = json!(binding.to_string());
    result["ledger_bytes"] = json!(std::fs::metadata(&ledger_path)?.len());
    result["witness_bytes"] = json!(std::fs::metadata(&witness_path)?.len());
    Ok(result)
}
fn main() -> Result<()> {
    let root = PathBuf::from(
        std::env::args()
            .nth(1)
            .ok_or("Explicit local research ledger root required")?,
    )
    .canonicalize()?;
    let permit: Value = serde_json::from_slice(&std::fs::read(root.join("RESEARCH_PERMIT.json"))?)?;
    if permit["schema"] != "hepta.local-research.signed-credit-permit.v1"
        || permit["allowed_root"] != root.to_string_lossy().as_ref()
        || permit["production_credentials"] != false
        || permit["external_effects"] != false
    {
        return Err("Local signed-credit research scope mismatch".into());
    }
    let mut out = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let start = Instant::now();
        let result: Result<Value> = (|| {
            if line.len() > 131072 {
                return Err("Bounded request limit".into());
            }
            handle(&root, serde_json::from_str(&line)?)
        })();
        let micros = start.elapsed().as_micros() as u64;
        let envelope = match result {
            Ok(value) => json!({"ok":true,"result":value,"physical_rpc_micros":micros}),
            Err(error) => {
                json!({"ok":false,"error":format!("{error:?}"),"physical_rpc_micros":micros})
            }
        };
        writeln!(out, "{}", serde_json::to_string(&envelope)?)?;
        out.flush()?;
    }
    Ok(())
}
