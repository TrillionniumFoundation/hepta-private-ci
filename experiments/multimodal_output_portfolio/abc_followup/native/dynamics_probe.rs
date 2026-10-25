//! Replay the unchanged pure kernel against retained actual runtime eligibility.
mod head;
mod measure;
mod runtime_profile;
mod dynamics_profile;

use std::path::Path;
use codex_hepta_neuron::*;
use codex_hepta_types::{Digest32,StableId};
use serde_json::{json,Value};

#[global_allocator]
static ALLOCATOR:measure::ObservedAllocator=measure::ObservedAllocator;
type Result<T>=std::result::Result<T,Box<dyn std::error::Error>>;
const Q:i64=1<<24;

fn multiply(a:i64,b:i64)->i64 {
    let p=i128::from(a)*i128::from(b);let m=p.abs();let q=m/i128::from(Q);let r=m%i128::from(Q);
    let up=r*2>i128::from(Q)||(r*2==i128::from(Q)&&q%2!=0);
    ((q+i128::from(up))*p.signum()) as i64
}

fn main()->Result<()> {
    let args:Vec<String>=std::env::args().collect();
    if args.len()!=4 {return Err("Usage: dynamics-probe packet actual-ticks-jsonl new-report".into());}
    let packet:Value=serde_json::from_slice(&std::fs::read(&args[1])?)?;
    let pins:runtime_profile::Pins=serde_json::from_value(packet["pins"].clone())?;
    let (mut config,mut runtime)=runtime_profile::configuration(&pins,Digest32::of_bytes(b"explicit-pure-kernel-diagnostic"))?;
    let profile=serde_json::from_value(packet.get("dynamics_profile").cloned().unwrap_or(json!("legacy")))?;
    dynamics_profile::bind(&mut config,&mut runtime,profile,dynamics_profile::DriveDomain::HistoricalSemanticPrefix)?;
    runtime.calibration.expires_after_sequence=1600;
    let mut model=head::LearnedHead {weights:serde_json::from_slice(&std::fs::read(packet["weights_path"].as_str().ok_or("weights")?)?)?,
        calibration:serde_json::from_slice(&std::fs::read(packet["calibration_path"].as_str().ok_or("calibration")?)?)?,
        config:runtime.clone(),measured_resident_heap_bytes:0};
    let observations:Vec<Value>=std::fs::read_to_string(&args[2])?.lines().map(serde_json::from_str).collect::<std::result::Result<_,_>>()?;
    let rows=packet["rows"].as_array().ok_or("packet rows")?;
    if rows.len()!=observations.len() {return Err("Retained census mismatch".into());}
    let mut previous:Option<SparseCheckpoint>=None;let mut activity=vec![0_i64;config.width];
    let mut first_exceeded=None;let mut decomposition=Vec::new();let mut failed=0;let mut matched=0;
    for (index,(row,actual)) in rows.iter().zip(&observations).enumerate() {
        let features:Vec<i64>=serde_json::from_value(row["features"].clone())?;
        let request=NeuronModelRequestV1 {request_id:StableId::new(format!("diagnostic.{}",index+1))?,
            config_id:runtime.config_id.clone(),generation:runtime.generation,model_id:runtime.model_id.clone(),
            encoder_digest:runtime.encoder_digest,head_digest:runtime.head_digest,weights_digest:runtime.weights_digest,
            input_digest:canonical_feature_vector_digest_v1(&features),feature_vector_q24:features,expected_output_width:32};
        measure::start_window();let output=model.execute(&request)?;
        let bind=Digest32::of_bytes(b"research-replay-binding-not-native-authority");
        let input=SparseTick {scope_digest:bind,objective_digest:pins.protocol.parse()?,ndu_digest:bind,body_digest:bind,
            input_digest:request.input_digest,sequence:index as u64+1,monotonic_micros:index as u64+1,
            drive_q24:output.drive_q24,prediction_q24:output.prediction_q24};
        let (state,receipt)=sparse_tick(&config,&input,previous.as_ref())?;
        if state.eligibility_digest().to_string()!=actual["eligibility_digest"].as_str().ok_or("eligibility")?
            || receipt.active_fraction_ppm as u64!=actual["active_fraction_ppm"].as_u64().ok_or("activity")?
        {return Err("Pure kernel does not reproduce actual runtime state".into());}
        matched+=1;let mut threshold_clips=0;let mut continuing_clips=0;let mut lower=0;let mut upper=0;
        for (j,rate) in activity.iter_mut().enumerate() {
            let active=if receipt.activation_q24[j]>0 {Q} else {0};
            *rate=multiply(config.activity_decay_q24,*rate)+multiply(Q-config.activity_decay_q24,active);
            let old=previous.as_ref().map_or(0,|p|p.thresholds_q24()[j]);
            let raw=old+multiply(config.threshold_rate_q24,*rate-config.target_activity_q24);
            let clipped=raw.clamp(config.threshold_min_q24,config.threshold_max_q24);
            if clipped!=state.thresholds_q24()[j] {return Err("Diagnostic homeostasis decomposition mismatch".into());}
            if clipped!=raw {threshold_clips+=1;if old==clipped {continuing_clips+=1;}}
            lower+=usize::from(clipped==config.threshold_min_q24);upper+=usize::from(clipped==config.threshold_max_q24);
        }
        if receipt.projection_count>8 {failed+=1;if first_exceeded.is_none() {first_exceeded=Some(index+1);}}
        decomposition.push(json!({"sequence":index+1,"pair":row["pair"],"declared_ood":row["declared_ood"],
            "actual_abstain":actual["abstain"],"actual_confidence_ppm":actual["confidence_ppm"],
            "projection_count":receipt.projection_count,"threshold_clips":threshold_clips,
            "already_at_bound_threshold_clips":continuing_clips,"at_lower_bound":lower,"at_upper_bound":upper,
            "other_projections":receipt.projection_count-threshold_clips,
            "drive_q24":input.drive_q24,"thresholds_q24":state.thresholds_q24()}));
        previous=Some(state);
    }
    let report=json!({"schema":"hepta.abc4.actual-state-dynamics-replay.v1","actual_eligibility_matches":matched,
        "first_projection_gate_exceeded_sequence":first_exceeded,"ticks_exceeding_projection_gate":failed,
        "config_changed":false,"gate_changed":false,"authority":"deny_all","ticks":decomposition,
        "scope":"unchanged original pure sparse_tick reproduces actual retained runtime state; diagnostic bindings are not authority"});
    let path=Path::new(&args[3]);let mut file=std::fs::File::create_new(path)?;
    use std::io::Write;file.write_all(&serde_json::to_vec(&report)?)?;file.sync_all()?;
    println!("{}",json!({"matches":matched,"first_projection_gate_exceeded_sequence":first_exceeded,"projection_gate_exceeded_ticks":failed}));Ok(())
}
