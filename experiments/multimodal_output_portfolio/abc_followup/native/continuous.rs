//! Continuous actual NeuronRuntime, bounded rollover and acknowledged recovery.
mod head;
mod future_head;
mod measure;
mod runtime_profile;
mod stream_io;
mod dynamics_profile;
mod proposal_hook;

use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::time::Instant;

use codex_hepta_ndu::{NduProjectionKindV1,NduProjectionStoreV1};
use codex_hepta_neuron::*;
use codex_hepta_types::{Digest32,FixedQ32,StableId};
use codex_native_owner_bridge::plasticity_modulator_digest_v1;
use serde::Deserialize;
use serde_json::json;
use stream_io::{file,Result,SEGMENT};

#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;

#[derive(Deserialize)]
struct Row {
    pair:usize,features:Vec<i64>,confidence_ppm:u32,ood_ppm:u32,declared_ood:bool,
    joint_correct:u8,terminal_value_q32:i64,observed_record_digest:String,source_pair_digest:String,
    #[serde(default)] expected_prediction:Option<Vec<i64>>,
}

#[derive(Deserialize)]
struct Packet {
    pins:runtime_profile::Pins,rows:Vec<Row>,weights_path:String,calibration_path:String,verification_path:String,
    #[serde(default)] future_output_model:bool,
    #[serde(default)] future_contract:future_head::OutputContract,
    #[serde(default)] study_qualified:Option<bool>,
    #[serde(default)] dynamics_profile:dynamics_profile::DynamicsProfile,
    #[serde(default)] live_proposal:Option<proposal_hook::Hook>,
}

enum Model {Current(head::LearnedHead),Future(future_head::FutureHead)}
impl NeuronModelPort for Model {
    fn execute(&mut self,request:&NeuronModelRequestV1)->std::result::Result<NeuronModelOutputV1,NeuronModelError> {
        let (output,domain)=match self {
            Self::Current(m)=>(m.execute(request)?,dynamics_profile::DriveDomain::HistoricalSemanticPrefix),
            Self::Future(m)=>(m.execute(request)?,dynamics_profile::DriveDomain::FutureEmittedState),
        };
        if output.drive_q24.iter().any(|v|v.abs()>dynamics_profile::bound(domain)) {
            return Err(NeuronModelError::Rejected);
        }
        Ok(output)
    }
}

fn checked(path:&str,expected:&str)->Result<Vec<u8>> {
    let bytes=std::fs::read(path)?;
    if Digest32::of_bytes(&bytes).to_string()!=expected {return Err("Pinned input changed".into());}
    Ok(bytes)
}

fn quantile(values:&[u64],p:usize)->u64 {
    let mut sorted=values.to_vec();sorted.sort_unstable();sorted[(sorted.len()*p).div_ceil(100)-1]
}

fn main()->Result<()> {
    let started=Instant::now();let args:Vec<String>=std::env::args().collect();
    if args.len()!=4 {return Err("Usage: native-continuous packet expected-sha new-output".into());}
    let packet:Packet=serde_json::from_slice(&checked(&args[1],&args[2])?)?;
    let output=Path::new(&args[3]);std::fs::create_dir(output)?;
    let weights=checked(&packet.weights_path,&packet.pins.weights)?;
    let calibration=checked(&packet.calibration_path,&packet.pins.calibration)?;
    let verification=checked(&packet.verification_path,&packet.pins.verification)?;
    let verified:serde_json::Value=serde_json::from_slice(&verification)?;
    if verified["native_measured_ece_ppm"].as_u64()!=Some(packet.pins.measured_ece_ppm as u64)
        || verified["native_measured_false_acceptance_ppm"].as_u64()!=Some(packet.pins.measured_false_acceptance_ppm as u64)
    {return Err("Measured qualification differs from pinned verification".into());}
    if packet.future_output_model && (packet.study_qualified.is_none()
        || matches!(packet.future_contract,future_head::OutputContract::FutureCorrectness)
            && packet.study_qualified!=verified["study_qualified"].as_bool())
    {return Err("Future study gate missing or differs from pinned complete qualification".into());}
    let binary=Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
    let (mut native,mut config)=runtime_profile::configuration(&packet.pins,binary)?;
    config.config_id=StableId::new("abc4.continuous.bound-profile")?;
    config.calibration.expires_after_sequence=packet.rows.len() as u64;
    if packet.future_output_model {
        native.width=33;config.state_width=33;config.input_feature_dimension=510;
        config.model_id=StableId::new(match packet.future_contract {
            future_head::OutputContract::StateResidual=>"abc4.causal-future-output.v1",
            future_head::OutputContract::FutureCorrectness=>"abc4.causal-future-correctness.v1",
        })?;
        native.normalization_digest=Digest32::of_bytes(match packet.future_contract {
            future_head::OutputContract::StateResidual=>b"abc4.actual-future-state-residual.no-scaling.v1".as_slice(),
            future_head::OutputContract::FutureCorrectness=>b"abc4.future-probability-carrier.observed-coordinates-cancel.v1".as_slice(),
        });
        config.normalization_digest=native.normalization_digest;
        config.native_config_digest=native.digest()?;
    }
    let domain=if packet.future_output_model {dynamics_profile::DriveDomain::FutureEmittedState}
        else {dynamics_profile::DriveDomain::HistoricalSemanticPrefix};
    dynamics_profile::bind(&mut native,&mut config,packet.dynamics_profile,domain)?;
    let heap=measure::live_bytes();
    let mut model=if packet.future_output_model {Model::Future(future_head::FutureHead {
        weights:serde_json::from_slice(&weights)?,calibration:serde_json::from_slice(&calibration)?,
        config:config.clone(),contract:packet.future_contract,measured_resident_heap_bytes:0,
    })} else {Model::Current(head::LearnedHead {
        weights:serde_json::from_slice(&weights)?,calibration:serde_json::from_slice(&calibration)?,
        config:config.clone(),measured_resident_heap_bytes:0,
    })};
    let resident=measure::live_bytes()-heap;
    match &mut model {Model::Current(m)=>m.measured_resident_heap_bytes=resident,Model::Future(m)=>m.measured_resident_heap_bytes=resident}
    // This executes the learned Rust head independently of admission. A refused
    // profile remains refused; raw prediction execution grants no tick authority.
    let mut parity=0;
    for (i,row) in packet.rows.iter().enumerate() {
        let request=NeuronModelRequestV1 {request_id:StableId::new(format!("abc4.parity.{i}"))?,
            config_id:config.config_id.clone(),generation:config.generation,model_id:config.model_id.clone(),
            encoder_digest:config.encoder_digest,head_digest:config.head_digest,weights_digest:config.weights_digest,
            input_digest:canonical_feature_vector_digest_v1(&row.features),feature_vector_q24:row.features.clone(),
            expected_output_width:config.state_width};
        measure::start_window();
        let predicted=model.execute(&request)?;
        let error=predicted.drive_q24.iter().zip(&predicted.prediction_q24)
            .map(|(a,b)|a.abs_diff(*b)).max().ok_or("Empty model output")?;
        let ood=(error*1_000_000/(1<<24)).min(1_000_000) as u32;
        if (1_000_000-ood,ood)!=(row.confidence_ppm,row.ood_ppm)
            || row.expected_prediction.as_ref().is_some_and(|q|q!=&predicted.prediction_q24)
        {return Err("Rust forecast/calibration differs from pinned Python prediction".into());}
        parity+=1;
    }
    let subject=StableId::new("abc4.continuous.research-subject")?;
    let objective:Digest32=packet.pins.protocol.parse()?;
    let scope=JournalScope {scope_digest:runtime_profile::subject_scope(&subject),objective_digest:objective};
    let root=output.join("case-0000");std::fs::create_dir(&root)?;
    let witness=FileAnchorWitnessStore::open(file(&root.join("neuron.witness"))?,scope,native.generation,4096)?;
    let attempt=NeuronRuntime::bootstrap(file(&root.join("neuron-0000.journal"))?,native.clone(),scope,SEGMENT,config.clone(),witness);
    let mut runtime=match attempt {
        Ok(value)=>value,
        Err(error)=>{
            let report=json!({"schema":"hepta.abc4.native-continuous.v1","packet_sha256":args[2],
                "binary_sha256":binary.to_string(),"future_output_model":packet.future_output_model,
                "future_contract":format!("{:?}",packet.future_contract),
                "raw_resident_model_predictions":parity,"actual_runtime_bootstrap_called":true,
                "runtime_bootstrap":"rejected","runtime_error":format!("{error:?}"),
                "measured_ece_ppm":packet.pins.measured_ece_ppm,"maximum_ece_ppm":30000,
                "real_native_runtime_ticks":0,"new_independent_samples":0,"authority":"deny_all",
                "applied_model_update":false,"process_wall_micros":started.elapsed().as_micros()});
            std::fs::write(output.join("result.json"),serde_json::to_vec_pretty(&report)?)?;
            println!("{report}");return Ok(());
        }
    };
    if packet.study_qualified==Some(false) {
        let report=json!({"schema":"hepta.abc4.native-continuous.v1","packet_sha256":args[2],
            "binary_sha256":binary.to_string(),"future_contract":format!("{:?}",packet.future_contract),
            "raw_resident_model_predictions":parity,"actual_runtime_bootstrap_called":true,
            "runtime_bootstrap":"accepted","study_gate":"rejected","real_native_runtime_ticks":0,
            "new_independent_samples":0,"authority":"deny_all","applied_model_update":false});
        std::fs::write(output.join("result.json"),serde_json::to_vec_pretty(&report)?)?;
        println!("{report}");return Ok(());
    }
    let ndu_root=root.join("ndu");std::fs::create_dir(&ndu_root)?;
    let mut ndu=NduProjectionStoreV1::open(&ndu_root)?;
    let mut records=File::create_new(output.join("ticks.jsonl"))?;
    let mut outer=Vec::new();let mut samples=Vec::new();let mut admitted_id=0;let mut admitted_ood=0;
    let mut rollovers=0;let mut recoveries=0;let mut final_context=json!({});let mut live_proposal=None;
    for (index,row) in packet.rows.iter().enumerate() {
        if index>0 && index%SEGMENT==0 {
            runtime.rollover(file(&root.join(format!("neuron-{:04}.journal",index/SEGMENT)))?,SEGMENT)?;
            rollovers+=1;
        }
        let previous=runtime.current_anchor()?.map_or(Digest32::ZERO,|a|a.checkpoint_digest);
        let modulator=plasticity_modulator_digest_v1(objective,scope.scope_digest,&[FixedQ32::from_raw(row.terminal_value_q32)])?;
        let observation:Digest32=row.observed_record_digest.parse()?;
        ndu.append_projection(NduProjectionKindV1::Utility,observation,objective,scope.scope_digest,modulator)?;
        ndu.select_projection(Digest32::of_bytes(format!("{observation}:selected:{index}").as_bytes()),objective,scope.scope_digest,modulator)?;
        let input=NeuronTickInputV1 {tick_id:StableId::new(format!("abc4.tick.{}",index+1))?,subject_id:subject.clone(),
            logical_sequence:index as u64+1,monotonic_time_micros:started.elapsed().as_micros() as u64,checkpoint_digest:previous,
            input_feature_digest:canonical_feature_vector_digest_v1(&row.features),feature_vector_q24:row.features.clone(),
            objective_digest:objective,ndu_snapshot_digest:modulator,body_generation:Some(1),modulator_digest:Some(modulator)};
        measure::start_window();
        let began=Instant::now();let result=runtime.tick(&mut model,input)?;let wall=began.elapsed().as_micros() as u64;
        let anchor=runtime.current_anchor()?.ok_or("No acknowledged anchor")?;
        let eligibility=runtime.current_eligibility_sample()?.ok_or("No eligibility")?;
        if result.tick.confidence_ppm!=row.confidence_ppm || result.tick.ood_ppm!=row.ood_ppm {
            return Err("Continuous runtime changed prediction confidence".into());
        }
        if !result.tick.abstain {if row.declared_ood {admitted_ood+=1;}else {admitted_id+=1;}}
        samples.push(NeuronResourceSampleV1 {host_profile_digest:config.device_digest,exact_candidate_digest:config.model_manifest_digest,
            observed_at_micros:index as u64+1,receipt:result.tick.resource_receipt.clone()});outer.push(wall);
        let checkpoint=runtime.canonical_checkpoint(&result.tick,u64::MAX)?;
        let record=json!({"pair":row.pair,"sequence":index+1,"subject_scope":scope.scope_digest.to_string(),
            "objective":objective.to_string(),"anchor":anchor.checkpoint_digest.to_string(),"predecessor_anchor":previous.to_string(),
            "confidence_ppm":result.tick.confidence_ppm,"ood_ppm":result.tick.ood_ppm,"abstain":result.tick.abstain,
            "saturation_count":result.tick.resource_receipt.saturation_count,
            "native_execution_micros":result.tick.resource_receipt.execution_micros,
            "active_fraction_ppm":result.tick.active_indices.len()*1_000_000/config.state_width,"joint_correct":row.joint_correct,
            "declared_ood":row.declared_ood,"eligibility_q24":eligibility.eligibility_q24(),
            "eligibility_digest":result.tick.eligibility_digest.to_string(),"outer_tick_micros":wall,
            "ndu_modulator":modulator.to_string(),"ndu_terminal_q32":row.terminal_value_q32,
            "source_pair_digest":row.source_pair_digest,"observed_record_digest":row.observed_record_digest,"authority":"deny_all"});
        writeln!(records,"{record}")?;
        if let Some(hook)=packet.live_proposal.as_ref()
            && live_proposal.is_none() && index+1>=800 && !row.declared_ood && !result.tick.abstain {
            records.sync_all()?;
            std::fs::write(root.join("context.json"),serde_json::to_vec_pretty(&record)?)?;
            std::fs::write(root.join("checkpoint.bin"),encode_neuron_checkpoint_v1(&checkpoint)?)?;
            std::fs::write(root.join("ndu.backup"),ndu.backup_bytes()?)?;
            std::fs::write(output.join("result.json"),serde_json::to_vec_pretty(&json!({
                "packet_sha256":args[2],"binary_sha256":binary.to_string(),"future_output_model":packet.future_output_model,
                "status":"paused_at_actual_admitted_anchor","sequence":index+1}))?)?;
            drop(runtime);
            let mut pending=proposal_hook::run(hook,&args[1],&args[2],output,&record,packet.future_output_model)?;
            runtime=stream_io::recover(&root,native.clone(),scope,config.clone(),index+1)?;
            if runtime.current_anchor()!=Ok(Some(anchor)) || runtime.current_eligibility_sample()?.as_ref()!=Some(&eligibility) {
                return Err("Live proposal handoff changed acknowledged runtime state".into());
            }
            pending["same_context_runtime_recovered_after_proposal"]=json!(true);live_proposal=Some(pending);recoveries+=1;
        }
        if index+1==packet.rows.len()/2 || index+1==packet.rows.len() {
            drop(runtime);runtime=stream_io::recover(&root,native.clone(),scope,config.clone(),index+1)?;
            if runtime.current_anchor()!=Ok(Some(anchor)) || runtime.current_eligibility_sample()?.as_ref()!=Some(&eligibility) {
                return Err("Midstream/final recovery changed acknowledged state".into());
            }
            recoveries+=1;
        }
        if index+1==packet.rows.len() {
            std::fs::write(root.join("checkpoint.bin"),encode_neuron_checkpoint_v1(&checkpoint)?)?;
            final_context=record;
        }
    }
    records.sync_all()?;
    std::fs::write(root.join("context.json"),serde_json::to_vec_pretty(&final_context)?)?;
    std::fs::write(root.join("ndu.backup"),ndu.backup_bytes()?)?;
    let resources=summarize_resource_samples(&samples,&config.resource_envelope)?;
    let report=json!({"schema":"hepta.abc4.native-continuous.v1","packet_sha256":args[2],"binary_sha256":binary.to_string(),
        "future_output_model":packet.future_output_model,"raw_resident_model_predictions":parity,
        "future_contract":format!("{:?}",packet.future_contract),
        "dynamics_profile":format!("{:?}",packet.dynamics_profile),
        "declared_drive_bound_q24":dynamics_profile::bound(domain),
        "threshold_min_q24":native.threshold_min_q24,"threshold_max_q24":native.threshold_max_q24,
        "target_activity_q24":native.target_activity_q24,"all_acceptance_gates_unchanged":true,
        "actual_runtime_bootstrap_called":true,"runtime_bootstrap":"accepted","real_native_runtime_ticks":samples.len(),
        "subject_contexts":1,"bounded_segment_capacity":SEGMENT,"segment_rollovers":rollovers,
        "same_context_acknowledged_recoveries":recoveries,"id_nonabstaining":admitted_id,"ood_nonabstaining":admitted_ood,
        "live_same_head_proposal":live_proposal,"live_proposal_required":packet.live_proposal.is_some(),
        "native_p95_micros":resources.p95_execution_micros,"native_p99_micros":resources.p99_execution_micros,
        "outer_p95_micros":quantile(&outer,95),"outer_p99_micros":quantile(&outer,99),
        "maximum_model_transient_allocation":resources.maximum_transient_allocation_bytes,
        "maximum_checkpoint_bytes":resources.maximum_checkpoint_bytes,"measured_resident_heap_bytes":resident,
        "resource_samples_pass":resources.pilot_ceiling_passed_for_supplied_samples,
        "final_anchor":final_context["anchor"],"final_sequence":final_context["sequence"],
        "final_pair":final_context["pair"],"final_abstain":final_context["abstain"],
        "process_wall_micros":started.elapsed().as_micros(),"new_independent_samples":0,
        "authority":"deny_all","production_admission":false,"applied_model_update":false,
        "scope":"one research subject across sequential observed tasks; not one uninterrupted long-horizon generation or production daemon"});
    std::fs::write(output.join("result.json"),serde_json::to_vec_pretty(&report)?)?;
    println!("{report}");
    if packet.live_proposal.is_some() && live_proposal.is_none() {return Err("No actual admitted ID checkpoint for required proposal hook".into());}
    Ok(())
}
