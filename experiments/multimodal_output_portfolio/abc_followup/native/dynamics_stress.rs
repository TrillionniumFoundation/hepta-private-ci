//! Full finite stress census, including correctly rejected silent transients.
mod head;
mod measure;
mod runtime_profile;
mod dynamics_profile;

use codex_hepta_neuron::{SparseCheckpoint,SparseTick,sparse_tick};
use codex_hepta_types::Digest32;
use serde_json::json;
use dynamics_profile::{DriveDomain,DynamicsProfile,bound,bind};

const Q:i64=1<<24;
type Result<T>=std::result::Result<T,Box<dyn std::error::Error>>;

fn main()->Result<()> {
    let args:Vec<String>=std::env::args().collect();
    if args.len()!=2 {return Err("Usage: dynamics-stress new-report".into());}
    let digest=Digest32::of_bytes(b"synthetic-finite-stress-not-production-evidence").to_string();
    let pins:runtime_profile::Pins=serde_json::from_value(json!({
        "protocol":digest,"feature_profile":digest,"weights":digest,"calibration":digest,
        "verification":digest,"device":digest,"upstream_model":digest,"source_manifest":digest,
        "dataset":digest,"measured_ece_ppm":0,"measured_false_acceptance_ppm":0,
    }))?;
    let mut cases=Vec::new();
    for (width,domain) in [(32,DriveDomain::HistoricalSemanticPrefix),(33,DriveDomain::FutureEmittedState)] {
        for pattern in 0..4 {
            let (mut config,mut runtime)=runtime_profile::configuration(&pins,digest.parse()?)?;
            config.width=width;runtime.state_width=width;
            bind(&mut config,&mut runtime,DynamicsProfile::BoundedBalanced,domain)?;
            let mut previous:Option<SparseCheckpoint>=None;let b=bound(domain);
            let mut silent=0;let mut maximum_projections=0;let mut projection_refusals=0;
            let mut first_silent=None;let mut last_silent=None;let mut longest_silent=0;let mut current_silent=0;
            for sequence in 1..=16384 {
                let mut drive=vec![0;width];drive[0]=Q;
                for (index,value) in drive.iter_mut().enumerate().skip(1) {
                    *value=match pattern {0=>b,1=>-b,2=>if sequence%2==0 {b}else {-b},
                        3=>if (index+sequence as usize)%width<4 {b}else {-b},_=>unreachable!()};
                }
                let d=Digest32::of_bytes(b"synthetic-bounded-stream");
                let input=SparseTick {scope_digest:d,objective_digest:d,ndu_digest:d,body_digest:d,
                    input_digest:d,sequence,monotonic_micros:sequence*1000,
                    prediction_q24:drive.clone(),drive_q24:drive};
                let (state,receipt)=sparse_tick(&config,&input,previous.as_ref())?;
                maximum_projections=maximum_projections.max(receipt.projection_count);
                projection_refusals+=usize::from(receipt.projection_count>8);
                if receipt.active_fraction_ppm<10000 {
                    silent+=1;first_silent.get_or_insert(sequence);last_silent=Some(sequence);
                    current_silent+=1;longest_silent=longest_silent.max(current_silent);
                }else {current_silent=0;}
                previous=Some(state);
            }
            cases.push(json!({"width":width,"pattern":pattern,"steps":16384,
                "maximum_projection_count":maximum_projections,"projection_refusals":projection_refusals,
                "silent_activity_refusals":silent,"first_silent_sequence":first_silent,
                "last_silent_sequence":last_silent,"longest_consecutive_silence":longest_silent,
                "all_steps_pass_activity_gate":silent==0,"new_independent_samples":0}));
        }
    }
    let report=json!({"schema":"hepta.abc4.bounded-dynamics-finite-stress.v1","cases":cases,
        "profile":"bounded_balanced","kernel_and_acceptance_gates_unchanged":true,
        "universal_stability_claim":false,"authority":"deny_all"});
    use std::io::Write;let mut file=std::fs::File::create_new(&args[1])?;
    file.write_all(&serde_json::to_vec_pretty(&report)?)?;file.sync_all()?;
    println!("{report}");Ok(())
}
