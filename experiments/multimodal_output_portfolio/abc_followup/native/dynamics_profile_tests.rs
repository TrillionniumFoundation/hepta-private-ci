use super::*;
use codex_hepta_neuron::{SparseCheckpoint,SparseTick,sparse_tick};
use codex_hepta_types::Digest32;

fn configuration(width:usize,profile:DynamicsProfile,domain:DriveDomain)->SparseConfig {
    let digest=Digest32::of_bytes(b"synthetic-dynamics-test-no-authority").to_string();
    let pins:crate::runtime_profile::Pins=serde_json::from_value(serde_json::json!({
        "protocol":digest,"feature_profile":digest,"weights":digest,"calibration":digest,
        "verification":digest,"device":digest,"upstream_model":digest,"source_manifest":digest,
        "dataset":digest,"measured_ece_ppm":0,"measured_false_acceptance_ppm":0,
    })).unwrap();
    let (mut native,mut runtime)=crate::runtime_profile::configuration(&pins,digest.parse().unwrap()).unwrap();
    native.width=width;runtime.state_width=width;
    bind(&mut native,&mut runtime,profile,domain).unwrap();native
}

#[test]
fn long_extreme_drives_stay_below_unchanged_projection_gate() {
    for (width,domain) in [(32,DriveDomain::HistoricalSemanticPrefix),(33,DriveDomain::FutureEmittedState)] {
        for pattern in 0..4 {
            let config=configuration(width,DynamicsProfile::BoundedBalanced,domain);
            let mut previous:Option<SparseCheckpoint>=None;let b=bound(domain);
            for sequence in 1..=16384 {
                let mut drive=vec![0;width];drive[0]=Q;
                for (index,value) in drive.iter_mut().enumerate().skip(1) {
                    *value=match pattern {0=>b,1=>-b,2=>if sequence%2==0 {b}else {-b},
                        3=>if (index+sequence as usize)%width<4 {b}else {-b},_=>unreachable!()};
                }
                let digest=Digest32::of_bytes(b"synthetic-bounded-stream");
                let input=SparseTick {scope_digest:digest,objective_digest:digest,ndu_digest:digest,
                    body_digest:digest,input_digest:digest,sequence,monotonic_micros:sequence*1000,
                    prediction_q24:drive.clone(),drive_q24:drive};
                let (state,receipt)=sparse_tick(&config,&input,previous.as_ref()).unwrap();
                assert!(receipt.projection_count<=8,"width{width} pattern{pattern} sequence{sequence}: {}",receipt.projection_count);
                // Activity can transiently be zero for in-domain extreme
                // inputs. The original runtime must still abstain then; this
                // invariant concerns projection saturation, not all-tick
                // admission. The complete census is in dynamics_stress.rs.
                previous=Some(state);
            }
        }
    }
}

#[test]
fn profile_rejects_changed_recurrence_premise() {
    let (mut bad,mut runtime)={
        let valid=configuration(32,DynamicsProfile::Legacy,DriveDomain::HistoricalSemanticPrefix);
        let digest=Digest32::of_bytes(b"invalid-dynamics-premise").to_string();
        let pins:crate::runtime_profile::Pins=serde_json::from_value(serde_json::json!({
            "protocol":digest,"feature_profile":digest,"weights":digest,"calibration":digest,
            "verification":digest,"device":digest,"upstream_model":digest,"source_manifest":digest,
            "dataset":digest,"measured_ece_ppm":0,"measured_false_acceptance_ppm":0,
        })).unwrap();
        (valid,crate::runtime_profile::configuration(&pins,digest.parse().unwrap()).unwrap().1)
    };
    bad.temporal_decay_q24=Q;
    assert!(bind(&mut bad,&mut runtime,DynamicsProfile::BoundedBalanced,DriveDomain::HistoricalSemanticPrefix).is_err());
}
